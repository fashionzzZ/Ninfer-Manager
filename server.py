#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ninfer Manager Backend Server
Provides hardware metrics, process lifecycle control, SSE log streaming,
presets management, and API proxy for Ninfer inference engine.
"""

import os
import sys
import time
import json
import socket
import shutil
import ctypes
import signal
import urllib.request
import urllib.error
import threading
import subprocess
import re
from collections import deque
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Reconfigure Windows stdout/stderr to utf-8 safely
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
PRESETS_FILE = os.path.join(BASE_DIR, "presets.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOGS_FILE = os.path.join(BASE_DIR, "ninfer_engine.log")

# -------------------------------------------------------------
# Win32 Hardware Monitoring (Pure ctypes + nvidia-smi)
# -------------------------------------------------------------

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ('dwLength', ctypes.c_ulong),
        ('dwMemoryLoad', ctypes.c_ulong),
        ('ullTotalPhys', ctypes.c_ulonglong),
        ('ullAvailPhys', ctypes.c_ulonglong),
        ('ullTotalPageFile', ctypes.c_ulonglong),
        ('ullAvailPageFile', ctypes.c_ulonglong),
        ('ullTotalVirtual', ctypes.c_ulonglong),
        ('ullAvailVirtual', ctypes.c_ulonglong),
        ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
    ]

class FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', ctypes.c_uint), ('dwHighDateTime', ctypes.c_uint)]

def _filetime_to_int(ft):
    return (ft.dwHighDateTime << 32) + ft.dwLowDateTime

class HardwareMonitor:
    def __init__(self):
        self._prev_idle = 0
        self._prev_kernel = 0
        self._prev_user = 0
        self._cached_metrics = {
            "timestamp": time.time(),
            "cpu_percent": 0.0,
            "ram_total_gb": 0.0,
            "ram_used_gb": 0.0,
            "ram_free_gb": 0.0,
            "ram_percent": 0.0,
            "gpu_available": False,
            "gpu_name": "N/A",
            "gpu_util_percent": 0.0,
            "vram_total_mb": 0.0,
            "vram_used_mb": 0.0,
            "vram_free_mb": 0.0,
            "vram_percent": 0.0,
            "gpu_temp_c": 0,
            "gpu_power_w": 0.0,
            "gpu_processes": []
        }
        self._lock = threading.Lock()
        self._init_cpu()
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def _init_cpu(self):
        try:
            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                self._prev_idle = _filetime_to_int(idle)
                self._prev_kernel = _filetime_to_int(kernel)
                self._prev_user = _filetime_to_int(user)
        except Exception:
            pass

    def _get_cpu_percent(self):
        try:
            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return 0.0
            cur_idle = _filetime_to_int(idle)
            cur_kernel = _filetime_to_int(kernel)
            cur_user = _filetime_to_int(user)

            d_idle = cur_idle - self._prev_idle
            d_kernel = cur_kernel - self._prev_kernel
            d_user = cur_user - self._prev_user

            self._prev_idle = cur_idle
            self._prev_kernel = cur_kernel
            self._prev_user = cur_user

            total = d_kernel + d_user
            if total > 0:
                percent = ((total - d_idle) * 100.0) / total
                return max(0.0, min(100.0, round(percent, 1)))
        except Exception:
            pass
        return 0.0

    def _get_ram_info(self):
        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_gb = stat.ullTotalPhys / (1024 ** 3)
                free_gb = stat.ullAvailPhys / (1024 ** 3)
                used_gb = total_gb - free_gb
                return round(total_gb, 2), round(used_gb, 2), round(free_gb, 2), round(float(stat.dwMemoryLoad), 1)
        except Exception:
            pass
        return 0.0, 0.0, 0.0, 0.0

    def _get_gpu_info(self):
        try:
            # Query nvidia-smi for basic stats
            cmd = [
                'nvidia-smi',
                '--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw',
                '--format=csv,noheader,nounits'
            ]
            res = subprocess.check_output(cmd, encoding='utf-8', timeout=2).strip()
            parts = [p.strip() for p in res.split(',')]
            if len(parts) >= 7:
                name = parts[0]
                total = float(parts[1])
                used = float(parts[2])
                free = float(parts[3])
                util = float(parts[4])
                temp = int(float(parts[5]))
                power = float(parts[6])
                pct = round((used / total) * 100.0, 1) if total > 0 else 0.0

                # Query process list
                processes = []
                try:
                    p_cmd = [
                        'nvidia-smi',
                        '--query-compute-apps=pid,process_name,used_gpu_memory',
                        '--format=csv,noheader,nounits'
                    ]
                    p_res = subprocess.check_output(p_cmd, encoding='utf-8', timeout=2).strip()
                    if p_res:
                        for line in p_res.splitlines():
                            p_parts = [p.strip() for p in line.split(',')]
                            if len(p_parts) >= 3:
                                processes.append({
                                    "pid": p_parts[0],
                                    "name": os.path.basename(p_parts[1]),
                                    "vram_mb": p_parts[2]
                                })
                except Exception:
                    pass

                return True, name, util, total, used, free, pct, temp, power, processes
        except Exception:
            pass
        return False, "N/A", 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, []

    def _monitor_loop(self):
        while self._running:
            try:
                cpu = self._get_cpu_percent()
                total_ram, used_ram, free_ram, ram_pct = self._get_ram_info()
                gpu_ok, gpu_name, gpu_util, vram_tot, vram_used, vram_free, vram_pct, temp, power, procs = self._get_gpu_info()

                with self._lock:
                    self._cached_metrics = {
                        "timestamp": time.time(),
                        "cpu_percent": cpu,
                        "ram_total_gb": total_ram,
                        "ram_used_gb": used_ram,
                        "ram_free_gb": free_ram,
                        "ram_percent": ram_pct,
                        "gpu_available": gpu_ok,
                        "gpu_name": gpu_name,
                        "gpu_util_percent": gpu_util,
                        "vram_total_mb": vram_tot,
                        "vram_used_mb": vram_used,
                        "vram_free_mb": vram_free,
                        "vram_percent": vram_pct,
                        "gpu_temp_c": temp,
                        "gpu_power_w": power,
                        "gpu_processes": procs
                    }
            except Exception as e:
                pass
            time.sleep(1.0)

    def get_metrics(self):
        with self._lock:
            return dict(self._cached_metrics)

hardware_monitor = HardwareMonitor()


# -------------------------------------------------------------
# Process & Engine Manager
# -------------------------------------------------------------

class EngineManager:
    def __init__(self):
        self.process = None
        self.pid = None
        self.status = "stopped"  # stopped, starting, running, error
        self.start_time = 0
        self.exit_code = None
        self.error_message = ""
        self.current_config = {}
        self.current_cmdline = ""
        self.logs = deque(maxlen=4000)
        self.log_counter = 0
        self.sse_listeners = []
        self._lock = threading.Lock()
        self._monitor_thread = None
        self._health_thread = None
        self.is_healthy = False
        self.auto_restart = False
        self.stats = {
            "decode_tok_s": 0.0,
            "last_decode_tok_s": 0.0,
            "prefill_tok_s": 0.0,
            "ttft_ms": 0,
            "output_tokens": 0,
            "is_generating": False,
            "last_update": 0.0
        }

    def add_log(self, text, level="INFO"):
        self.log_counter += 1
        entry = {
            "id": self.log_counter,
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "text": text
        }
        with self._lock:
            self.logs.append(entry)
            listeners = list(self.sse_listeners)

        # Notify SSE listeners
        for queue in listeners:
            try:
                queue.put_nowait(entry)
            except Exception:
                pass

        # Also write to local file
        try:
            with open(LOGS_FILE, "a", encoding="utf-8", errors="replace") as f:
                f.write(f"[{entry['time']}] [{level}] {text}\n")
        except Exception:
            pass

    def is_port_open(self, host, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect((host, int(port)))
            s.close()
            return True
        except Exception:
            return False

    def build_command_and_env(self, config, validate_paths=True):
        engine_path = config.get("engine_path", "").strip()
        model_path = config.get("model_path", "").strip()

        if validate_paths:
            if not engine_path or not os.path.exists(engine_path):
                raise ValueError(f"引擎可执行文件不存在: {engine_path}")
            if not model_path or not os.path.exists(model_path):
                raise ValueError(f"模型文件不存在: {model_path}")

        engine_dir = os.path.dirname(os.path.abspath(engine_path)) if engine_path else "."

        # Setup Environment Variables
        env = os.environ.copy()
        env["CUDA_BIN"] = engine_dir
        cuda_x64 = os.path.join(engine_dir, "x64")
        env["PATH"] = f"{engine_dir};{cuda_x64};" + env.get("PATH", "")

        # Preset Env Vars
        env_vars = config.get("env_vars", {})
        for k, v in env_vars.items():
            if v is not None and str(v).strip() != "":
                env[k] = str(v).strip()

        # Build CLI Args
        args = [engine_path, model_path]

        # Host & Port
        host = config.get("host", "127.0.0.1")
        port = config.get("port", 8094)
        args.extend(["--host", str(host), "--port", str(port)])

        # Model ID
        model_id = config.get("model_id", "qwen3.8-27b").strip()
        if model_id:
            args.extend(["--model-id", model_id])

        # Context & Capacity
        max_context = config.get("max_context")
        if max_context:
            args.extend(["--max-context", str(max_context)])

        default_max_tokens = config.get("default_max_tokens")
        if default_max_tokens:
            args.extend(["--default-max-tokens", str(default_max_tokens)])

        kv_capacity = config.get("kv_capacity")
        if kv_capacity:
            args.extend(["--kv-capacity", str(kv_capacity)])

        kv_dtype = config.get("kv_dtype")
        if kv_dtype:
            args.extend(["--kv-dtype", str(kv_dtype)])

        host_kv_mib = config.get("host_kv_mib")
        if host_kv_mib:
            args.extend(["--host-kv-mib", str(host_kv_mib)])

        prefill_chunk = config.get("prefill_chunk")
        if prefill_chunk:
            args.extend(["--prefill-chunk", str(prefill_chunk)])

        # Speculative Decoding
        spec = config.get("spec")
        if spec and spec != "none":
            args.extend(["--spec", str(spec)])

        draft_tokens = config.get("draft_tokens")
        if draft_tokens and spec and spec != "none":
            args.extend(["--draft-tokens", str(draft_tokens)])

        if config.get("lm_head_draft"):
            args.append("--lm-head-draft")

        if config.get("vision"):
            args.append("--vision")

        # Performance & Precision Flags
        if config.get("no_cuda_graph"):
            args.append("--no-cuda-graph")

        if config.get("gdn_state_fp16"):
            args.append("--gdn-state-fp16")

        if config.get("rope_yarn"):
            args.append("--rope-yarn")

        # Cache & Continual
        max_long_anchors = config.get("max_long_anchors_per_continuation")
        if max_long_anchors is not None and str(max_long_anchors) != "":
            args.extend(["--max-long-anchors-per-continuation", str(max_long_anchors)])

        if config.get("release_diverged_checkpoints"):
            args.append("--release-diverged-checkpoints")

        if config.get("recover_invariant_failures"):
            args.append("--recover-invariant-failures")

        default_reasoning_effort = config.get("default_reasoning_effort")
        if default_reasoning_effort and default_reasoning_effort != "default":
            args.extend(["--default-reasoning-effort", str(default_reasoning_effort)])

        max_concurrency = config.get("max_concurrency")
        if max_concurrency:
            args.extend(["--max-concurrency", str(max_concurrency)])

        max_shared_prefixes = config.get("max_shared_prefixes")
        if max_shared_prefixes is not None and str(max_shared_prefixes) != "":
            args.extend(["--max-shared-prefixes", str(max_shared_prefixes)])

        # Sampling
        presence_penalty = config.get("presence_penalty")
        if presence_penalty is not None and str(presence_penalty) != "":
            args.extend(["--presence-penalty", str(presence_penalty)])

        temperature = config.get("temperature")
        if temperature is not None and str(temperature) != "":
            args.extend(["--temperature", str(temperature)])

        top_p = config.get("top_p")
        if top_p is not None and str(top_p) != "":
            args.extend(["--top-p", str(top_p)])

        top_k = config.get("top_k")
        if top_k is not None and str(top_k) != "":
            args.extend(["--top-k", str(top_k)])

        # Extra raw arguments
        extra_args = config.get("extra_args", "").strip()
        if extra_args:
            for part in extra_args.split():
                if part.strip():
                    args.append(part.strip())

        return args, env

    def start(self, config):
        with self._lock:
            if self.process and self.process.poll() is None:
                raise RuntimeError("引擎当前正在运行中，请先停止再启动！")

            self.status = "starting"
            self.error_message = ""
            self.exit_code = None
            self.is_healthy = False
            self.current_config = config
            self.auto_restart = config.get("auto_restart", False)

        try:
            # Check port conflict
            host = config.get("host", "127.0.0.1")
            port = int(config.get("port", 8094))
            if self.is_port_open(host, port):
                self.add_log(f"警告: 端口 {port} 已被占用，可能导致引擎启动失败！", "WARN")

            args, env = self.build_command_and_env(config)
            cmdline = subprocess.list2cmdline(args)
            self.current_cmdline = cmdline

            self.add_log(f"===========================================================", "INFO")
            self.add_log(f"正在启动 Ninfer 引擎...", "INFO")
            self.add_log(f"可执行文件: {args[0]}", "INFO")
            self.add_log(f"模型文件: {args[1]}", "INFO")
            self.add_log(f"服务地址: http://{host}:{port}", "INFO")
            self.add_log(f"完整命令行: {cmdline}", "DEBUG")
            self.add_log(f"===========================================================", "INFO")

            # Launch process with unbuffered pipe
            self.process = subprocess.Popen(
                args,
                env=env,
                cwd=os.path.dirname(args[0]),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace"
            )

            self.pid = self.process.pid
            self.start_time = time.time()
            self.status = "running"
            self.add_log(f"引擎进程已创建，PID: {self.pid}", "SUCCESS")

            # Start background stream reader
            log_filters = [f.strip().lower() for f in config.get("log_filters", []) if f.strip()]
            self._monitor_thread = threading.Thread(
                target=self._reader_loop,
                args=(self.process, log_filters),
                daemon=True
            )
            self._monitor_thread.start()

            # Start health check thread
            self._health_thread = threading.Thread(
                target=self._health_check_loop,
                args=(host, port),
                daemon=True
            )
            self._health_thread.start()

            return {"success": True, "pid": self.pid, "status": self.status}

        except Exception as e:
            self.status = "error"
            self.error_message = str(e)
            self.add_log(f"启动失败: {str(e)}", "ERROR")
            raise

    def _reader_loop(self, proc, filters):
        try:
            for line in proc.stdout:
                line_str = line.rstrip("\r\n")
                if not line_str:
                    continue

                # Parse real-time token throughput and request metrics
                try:
                    m_decode = re.search(r'decode\s+([\d\.]+)\s+tok/s', line_str)
                    m_prefill = re.search(r'prefill\s+([\d\.]+)\s+tok/s', line_str)
                    m_ttft = re.search(r'TTFT\s+(\d+)\s+ms', line_str)
                    m_out = re.search(r'output\s+(\d+)', line_str)

                    if "started" in lower_line and "req#" in lower_line:
                        with self._lock:
                            self.stats["is_generating"] = True
                            self.stats["last_update"] = time.time()

                    if m_decode:
                        spd = float(m_decode.group(1))
                        with self._lock:
                            self.stats["decode_tok_s"] = spd
                            if spd > 0:
                                self.stats["last_decode_tok_s"] = spd
                            self.stats["is_generating"] = True
                            self.stats["last_update"] = time.time()

                    if m_prefill:
                        with self._lock:
                            self.stats["prefill_tok_s"] = float(m_prefill.group(1))

                    if m_ttft:
                        with self._lock:
                            self.stats["ttft_ms"] = int(m_ttft.group(1))

                    if m_out:
                        with self._lock:
                            self.stats["output_tokens"] = int(m_out.group(1))

                    if "req#" in lower_line and ("done" in lower_line or "complete" in lower_line or "stop" in lower_line):
                        with self._lock:
                            self.stats["is_generating"] = False
                except Exception:
                    pass

                # Filter noise (e.g. "mask hidden", "demote-other")
                lower_line = line_str.lower()
                skip = False
                for flt in filters:
                    if flt in lower_line:
                        skip = True
                        break
                if skip:
                    continue

                # Determine log level
                level = "INFO"
                if "error" in lower_line or "fail" in lower_line or "refuse" in lower_line:
                    level = "ERROR"
                elif "warn" in lower_line:
                    level = "WARN"
                elif "kvmem_score" in lower_line or "select" in lower_line:
                    level = "KVMEM"
                elif "ready" in lower_line or "listening" in lower_line or "serve" in lower_line:
                    level = "SUCCESS"

                self.add_log(line_str, level)

        except Exception as e:
            self.add_log(f"日志读取异常: {e}", "WARN")
        finally:
            proc.wait()
            self.exit_code = proc.returncode
            self.add_log(f"引擎进程退出，退出代码: {self.exit_code}", "WARN" if self.exit_code == 0 else "ERROR")
            
            with self._lock:
                self.process = None
                self.pid = None
                self.is_healthy = False
                if self.status != "stopped":
                    self.status = "error" if self.exit_code != 0 else "stopped"

            # Auto restart if crashed and enabled
            if self.auto_restart and self.exit_code != 0:
                self.add_log("检测到进程异常退出，3秒后自动尝试重启...", "WARN")
                time.sleep(3.0)
                try:
                    self.start(self.current_config)
                except Exception as restart_err:
                    self.add_log(f"自动重启失败: {restart_err}", "ERROR")

    def _health_check_loop(self, host, port):
        # Poll HTTP endpoint
        url = f"http://{host}:{port}/v1/models"
        health_url = f"http://{host}:{port}/health"

        while self.process and self.process.poll() is None:
            time.sleep(1.5)
            # Try /v1/models or /health
            for target in [url, health_url]:
                try:
                    req = urllib.request.Request(target, headers={"User-Agent": "NinferManager/1.0"})
                    with urllib.request.urlopen(req, timeout=1.0) as resp:
                        if resp.status == 200:
                            if not self.is_healthy:
                                self.is_healthy = True
                                self.add_log(f"★ 引擎服务探针就绪！已在 http://{host}:{port} 提供推理服务", "SUCCESS")
                            break
                except Exception:
                    pass
            if self.is_healthy:
                break

    def stop(self):
        with self._lock:
            self.auto_restart = False
            proc = self.process

        if not proc or proc.poll() is not None:
            self.status = "stopped"
            self.process = None
            self.pid = None
            self.is_healthy = False
            return {"success": True, "message": "引擎未运行"}

        self.add_log(f"正在停止引擎进程 (PID: {proc.pid})...", "INFO")
        try:
            # Terminate gracefully via taskkill /T on Windows to kill tree
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        with self._lock:
            self.status = "stopped"
            self.process = None
            self.pid = None
            self.is_healthy = False

        self.add_log("引擎已成功停止。", "SUCCESS")
        return {"success": True, "status": "stopped"}

    def restart(self):
        config = dict(self.current_config)
        self.stop()
        time.sleep(1.0)
        return self.start(config)

    def get_status(self):
        is_running = self.process is not None and self.process.poll() is None
        uptime = int(time.time() - self.start_time) if is_running else 0

        # Speed decay when idle
        now = time.time()
        with self._lock:
            active_decode = self.stats["decode_tok_s"]
            if (now - self.stats["last_update"]) > 4.5:
                active_decode = 0.0
                self.stats["is_generating"] = False

            speed_info = {
                "decode_tok_s": round(active_decode, 1),
                "last_decode_tok_s": round(self.stats["last_decode_tok_s"], 1),
                "prefill_tok_s": round(self.stats["prefill_tok_s"], 1),
                "ttft_ms": self.stats["ttft_ms"],
                "output_tokens": self.stats["output_tokens"],
                "is_generating": self.stats["is_generating"]
            }

        return {
            "status": "running" if is_running else self.status,
            "pid": self.pid if is_running else None,
            "uptime_seconds": uptime,
            "is_healthy": self.is_healthy,
            "exit_code": self.exit_code,
            "error_message": self.error_message,
            "current_cmdline": self.current_cmdline,
            "host": self.current_config.get("host", "127.0.0.1"),
            "port": self.current_config.get("port", 8094),
            "model_id": self.current_config.get("model_id", "qwen3.8-27b"),
            "model_path": self.current_config.get("model_path", ""),
            "speed": speed_info
        }

engine_manager = EngineManager()


# -------------------------------------------------------------
# Presets & File Scanning Utilities
# -------------------------------------------------------------

def load_presets():
    if os.path.exists(PRESETS_FILE):
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_presets(presets):
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2, ensure_ascii=False)

def scan_model_files(search_paths):
    results = []
    seen = set()

    for p in search_paths:
        if not p or not os.path.exists(p):
            continue
        p = os.path.abspath(p)
        if os.path.isfile(p) and p.endswith(".ninfer"):
            if p not in seen:
                seen.add(p)
                size_gb = round(os.path.getsize(p) / (1024 ** 3), 2)
                results.append({
                    "name": os.path.basename(p),
                    "path": p,
                    "size_gb": size_gb,
                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p)))
                })
        elif os.path.isdir(p):
            try:
                for root, _, files in os.walk(p):
                    for file in files:
                        if file.endswith(".ninfer"):
                            full_path = os.path.abspath(os.path.join(root, file))
                            if full_path not in seen:
                                seen.add(full_path)
                                size_gb = round(os.path.getsize(full_path) / (1024 ** 3), 2)
                                results.append({
                                    "name": file,
                                    "path": full_path,
                                    "size_gb": size_gb,
                                    "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(full_path)))
                                })
            except Exception:
                pass
    return results

def generate_bat_script(config):
    lines = [
        "@echo off",
        "setlocal",
        f"set \"ENGINE={config.get('engine_path', '')}\"",
        f"set \"MODEL={config.get('model_path', '')}\"",
        "",
        "REM Environment variables",
        "set \"CUDA_BIN=%~dp0engine\"",
        "if not exist \"%CUDA_BIN%\" set \"CUDA_BIN=%ENGINE%\\..\"",
        "set \"PATH=%CUDA_BIN%;%CUDA_BIN%\\x64;%PATH%\"",
    ]

    env_vars = config.get("env_vars", {})
    for k, v in env_vars.items():
        if v is not None and str(v).strip() != "":
            lines.append(f"set \"{k}={v}\"")

    lines.append("")
    lines.append("echo [engine] %ENGINE%")
    lines.append("echo [model ] %MODEL%")
    lines.append("")

    args, _ = engine_manager.build_command_and_env(config, validate_paths=False)
    # Format command with caret ^
    cmd_parts = [f'"{args[0]}" "{args[1]}" ^']
    i = 2
    cur_line = " "
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            if len(cur_line.strip()) > 40:
                cmd_parts.append(cur_line + " ^")
                cur_line = "  " + arg
            else:
                cur_line += " " + arg
        else:
            cur_line += " " + arg
        i += 1
    if cur_line.strip():
        cmd_parts.append(cur_line)

    lines.extend(cmd_parts)
    lines.append("")
    lines.append("echo.")
    lines.append("echo [engine exited] errorlevel=%ERRORLEVEL%")
    lines.append("pause")
    return "\r\n".join(lines)


# -------------------------------------------------------------
# HTTP Request Handler
# -------------------------------------------------------------

class SilentThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Gracefully ignore client disconnects like WinError 10053, 10054, BrokenPipe
        err = sys.exc_info()[1]
        if isinstance(err, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        if isinstance(err, OSError) and getattr(err, "winerror", None) in (10053, 10054):
            return
        super().handle_error(request, client_address)

class NinferHttpHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except OSError as e:
            if getattr(e, "winerror", None) in (10053, 10054):
                pass
            else:
                raise

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True
        except OSError as e:
            if getattr(e, "winerror", None) in (10053, 10054):
                self.close_connection = True
            else:
                raise

    def log_message(self, format, *args):
        # Silence standard HTTP log spam
        pass

    def send_json(self, data, status=200):
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except OSError as e:
            if getattr(e, "winerror", None) in (10053, 10054):
                pass
            else:
                raise

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/system/status":
            metrics = hardware_monitor.get_metrics()
            engine_stat = engine_manager.get_status()
            self.send_json({"hardware": metrics, "engine": engine_stat})

        elif path == "/api/engine/status":
            self.send_json(engine_manager.get_status())

        elif path == "/api/logs":
            params = parse_qs(parsed.query)
            last_id = int(params.get("since", [0])[0])
            with engine_manager._lock:
                new_logs = [l for l in engine_manager.logs if l["id"] > last_id]
            self.send_json({"logs": new_logs, "total": len(engine_manager.logs)})

        elif path == "/api/logs/stream":
            self.handle_sse_stream()

        elif path == "/api/presets":
            presets = load_presets()
            self.send_json(presets)

        elif path == "/api/models":
            # Scans default locations
            default_locations = [
                r"D:\Ninfer\infer-engine-sm89-20261002\models",
                r"D:\Ninfer\models",
                os.path.join(BASE_DIR, "models")
            ]
            models = scan_model_files(default_locations)
            self.send_json(models)

        elif path == "/api/config":
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    self.send_json(cfg)
                    return
                except Exception:
                    pass
            self.send_json({})

        else:
            # Fallback to static files
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
        try:
            body = json.loads(raw_body)
        except Exception:
            body = {}

        if path == "/api/engine/start":
            try:
                res = engine_manager.start(body)
                # Persist active configuration
                try:
                    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                        json.dump(body, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=400)

        elif path == "/api/engine/stop":
            res = engine_manager.stop()
            self.send_json(res)

        elif path == "/api/engine/restart":
            try:
                res = engine_manager.restart()
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=400)

        elif path == "/api/logs/clear":
            with engine_manager._lock:
                engine_manager.logs.clear()
            self.send_json({"success": True})

        elif path == "/api/models/scan":
            custom_paths = body.get("paths", [])
            if not custom_paths:
                custom_paths = [
                    r"D:\Ninfer\infer-engine-sm89-20261002\models",
                    r"D:\Ninfer\models"
                ]
            models = scan_model_files(custom_paths)
            self.send_json(models)

        elif path == "/api/presets":
            # Save or update preset
            presets = load_presets()
            new_preset = body
            # Check if preset exists by id or name
            preset_id = new_preset.get("id") or str(int(time.time()))
            new_preset["id"] = preset_id

            found = False
            for i, p in enumerate(presets):
                if p.get("id") == preset_id:
                    presets[i] = new_preset
                    found = True
                    break
            if not found:
                presets.append(new_preset)

            save_presets(presets)
            self.send_json({"success": True, "presets": presets})

        elif path == "/api/presets/delete":
            preset_id = body.get("id")
            presets = load_presets()
            presets = [p for p in presets if p.get("id") != preset_id]
            save_presets(presets)
            self.send_json({"success": True, "presets": presets})

        elif path == "/api/export-bat":
            try:
                bat_text = generate_bat_script(body)
                self.send_json({"success": True, "bat_content": bat_text})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=400)

        elif path == "/api/chat":
            # Forward chat request to running engine
            self.handle_chat_proxy(body)

        else:
            self.send_json({"error": "Endpoint not found"}, status=404)

    def handle_sse_stream(self):
        """Server-Sent Events for real-time log pushing"""
        import queue
        q = queue.Queue(maxsize=500)
        with engine_manager._lock:
            engine_manager.sse_listeners.append(q)
            initial_logs = list(engine_manager.logs)[-100:]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        # Send initial backlog
        for item in initial_logs:
            data = f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            try:
                self.wfile.write(data.encode("utf-8"))
            except Exception:
                break
        self.wfile.flush()

        try:
            while True:
                try:
                    item = q.get(timeout=2.0)
                    data = f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                    self.wfile.write(data.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # Heartbeat
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except Exception:
            pass
        finally:
            with engine_manager._lock:
                if q in engine_manager.sse_listeners:
                    engine_manager.sse_listeners.remove(q)

    def handle_chat_proxy(self, req_data):
        host = engine_manager.current_config.get("host", "127.0.0.1")
        port = engine_manager.current_config.get("port", 8094)
        target_url = f"http://{host}:{port}/v1/chat/completions"

        try:
            req_json = json.dumps(req_data).encode("utf-8")
            req = urllib.request.Request(
                target_url,
                data=req_json,
                headers={"Content-Type": "application/json"}
            )
            is_stream = req_data.get("stream", False)

            if is_stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                t_start = time.time()
                t_first = 0.0
                tokens_est = 0
                with engine_manager._lock:
                    engine_manager.stats["is_generating"] = True
                    engine_manager.stats["last_update"] = time.time()

                try:
                    with urllib.request.urlopen(req, timeout=120) as upstream:
                        while True:
                            chunk = upstream.read(256)
                            if not chunk:
                                break
                            now = time.time()
                            if t_first == 0.0:
                                t_first = now
                                ttft = int((t_first - t_start) * 1000)
                                with engine_manager._lock:
                                    engine_manager.stats["ttft_ms"] = ttft

                            if b'"content"' in chunk:
                                tokens_est += chunk.count(b'"content"')
                                elapsed = now - t_first
                                if elapsed > 0.1:
                                    spd = tokens_est / elapsed
                                    with engine_manager._lock:
                                        engine_manager.stats["decode_tok_s"] = spd
                                        engine_manager.stats["last_decode_tok_s"] = spd
                                        engine_manager.stats["output_tokens"] = tokens_est
                                        engine_manager.stats["last_update"] = now

                            self.wfile.write(chunk)
                            self.wfile.flush()
                finally:
                    with engine_manager._lock:
                        engine_manager.stats["is_generating"] = False
            else:
                with urllib.request.urlopen(req, timeout=120) as upstream:
                    resp_body = upstream.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(resp_body)

        except Exception as e:
            self.send_json({"error": f"调用推理引擎失败: {str(e)}"}, status=502)


def _delayed_open_browser(url, delay=3.0):
    time.sleep(delay)
    # Wait until socket is responding
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9099
    ready = False
    for _ in range(12):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((host, port)) == 0:
                    ready = True
                    break
        except Exception:
            pass
        time.sleep(0.5)

    if ready:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

def run_server(port=9099, auto_open_browser=True):
    # Ensure static directory exists
    os.makedirs(STATIC_DIR, exist_ok=True)
    server_address = ("0.0.0.0", port)
    httpd = SilentThreadingHTTPServer(server_address, NinferHttpHandler)
    url = f"http://127.0.0.1:{port}"

    print("===========================================================")
    print("  [Ninfer] Model Launcher & Manager")
    print(f"  Web 控制台地址: {url}")
    print("===========================================================")
    print("  [状态] 后端服务已完全启动就绪")
    if auto_open_browser:
        print("  [状态] 浏览器将在 3 秒后自动弹出并载入控制台...")
        t_browser = threading.Thread(target=_delayed_open_browser, args=(url, 3.0), daemon=True)
        t_browser.start()
    print("-----------------------------------------------------------")
    print("  控制台操作指令:")
    print("    - 输入 'q' 或 'exit' 并按回车 : 停止所有引擎并安全退出程序")
    print("    - 输入 'status' 并按回车       : 查看当前引擎与硬件运行状态")
    print("    - 输入 'open' 并按回车         : 重新在浏览器中打开控制台")
    print("    - 输入 'help' 并按回车         : 查看指令帮助")
    print("    - 或直接按 Ctrl + C 快捷键退出")
    print("===========================================================")

    # Run server in daemon thread
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    # Interactive console command loop
    try:
        while True:
            try:
                if sys.stdin and sys.stdin.isatty():
                    sys.stdout.write("\n[Ninfer-Manager] 请输入指令 (输入 q 退出): ")
                    sys.stdout.flush()
                line = sys.stdin.readline()
                if not line:
                    # EOF reached in non-interactive environment
                    time.sleep(1.0)
                    continue
                cmd = line.strip().lower()
            except (EOFError, KeyboardInterrupt):
                cmd = "q"

            if cmd in ("q", "quit", "exit"):
                print("\n正在停止推理引擎进程并安全关闭服务...")
                engine_manager.stop()
                httpd.shutdown()
                httpd.server_close()
                print("所有服务已安全关闭，感谢使用！")
                break
            elif cmd in ("help", "h", "?"):
                print("\n[帮助菜单]")
                print("  q, quit, exit : 安全关闭并退出")
                print("  status        : 查看当前引擎与系统指标")
                print("  open          : 在默认浏览器中再次打开控制台")
            elif cmd == "status":
                eng = engine_manager.get_status()
                hw = hardware_monitor.get_metrics()
                print(f"\n[运行状态] 引擎: {eng['status']} | PID: {eng['pid']} | 运行: {eng['uptime_seconds']}s")
                print(f"[硬件指标] CPU: {hw['cpu_percent']}% | RAM: {hw['ram_used_gb']}/{hw['ram_total_gb']}GB | VRAM: {hw['vram_used_mb']/1024:.2f}/{hw['vram_total_mb']/1024:.2f}GB ({hw['vram_percent']}%)")
            elif cmd == "open":
                try:
                    import webbrowser
                    webbrowser.open(url)
                    print(f"已在浏览器中打开: {url}")
                except Exception as e:
                    print(f"打开浏览器失败: {e}")
            elif cmd == "":
                continue
            else:
                print(f"未知指令 '{cmd}'，输入 'help' 查看指令，输入 'q' 退出。")

    except KeyboardInterrupt:
        print("\n\n收到中断信号，正在停止推理引擎进程并安全关闭服务...")
        engine_manager.stop()
        httpd.shutdown()
        httpd.server_close()
        print("所有服务已安全关闭。")

if __name__ == "__main__":
    port = 9099
    auto_open = True
    for arg in sys.argv[1:]:
        if arg.isdigit():
            port = int(arg)
        elif arg == "--no-browser":
            auto_open = False
        elif arg == "--open-browser":
            auto_open = True
    run_server(port, auto_open)
