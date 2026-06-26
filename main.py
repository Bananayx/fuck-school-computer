import json
import logging
import os
import sys
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime


TASK_URL = "https://example.com/xxx.json"
POLL_INTERVAL_SECONDS = 60
LOG_FILE_NAME = "ed.log"
CONFIG_FILE_NAME = "config.json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, LOG_FILE_NAME)
CONFIG_FILE_PATH = os.path.join(BASE_DIR, CONFIG_FILE_NAME)


def setup_logger():
    logger = logging.getLogger("agent")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)
    return logger


log = setup_logger()


def load_executed_ids():
    executed = set()
    if not os.path.exists(LOG_FILE_PATH):
        return executed
    try:
        with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    tid = record.get("id")
                    if tid:
                        executed.add(tid)
                except json.JSONDecodeError:
                    parts = line.split("\t")
                    if len(parts) >= 2 and parts[1]:
                        executed.add(parts[1])
    except OSError as e:
        log.error("读取 %s 失败: %s", LOG_FILE_NAME, e)
    return executed


def mark_executed(task_id):
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "id": task_id,
    }
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log.error("写入 %s 失败: %s", LOG_FILE_NAME, e)


def fetch_tasks():
    log.info("正在从 %s 拉取任务声明", TASK_URL)
    try:
        req = urllib.request.Request(
            TASK_URL,
            headers={"User-Agent": "agent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8")
            payload = json.loads(data)
    except (urllib.error.URLError, TimeoutError) as e:
        log.error("拉取任务失败(网络): %s", e)
        return None
    except json.JSONDecodeError as e:
        log.error("任务数据解析失败: %s", e)
        return None
    except Exception as e:
        log.exception("拉取任务时发生未知错误: %s", e)
        return None

    if isinstance(payload, dict) and "tasks" in payload:
        payload = payload["tasks"]
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        log.error("任务数据格式应为列表或包含任务的对象，实际: %s", type(payload).__name__)
        return None
    return payload


def load_config_tasks():
    if not os.path.exists(CONFIG_FILE_PATH):
        log.info("未找到 %s，将仅依赖远程拉取", CONFIG_FILE_NAME)
        return []
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.error("读取 %s 失败: %s", CONFIG_FILE_NAME, e)
        return []

    if isinstance(data, dict) and "tasks" in data:
        data = data["tasks"]
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        log.error("%s 格式错误", CONFIG_FILE_NAME)
        return []
    return data


def parse_task_time(time_val):
    if time_val is None:
        return None
    if isinstance(time_val, (int, float)):
        try:
            return datetime.fromtimestamp(float(time_val))
        except (OSError, ValueError):
            return None
    if isinstance(time_val, str):
        s = time_val.strip()
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromtimestamp(float(s))
        except (ValueError, OSError):
            return None
    return None


def execute_code(code, task_id):
    log.info("开始执行任务 id=%s", task_id)
    try:
        exec_globals = {
            "__name__": "__task__",
            "__file__": CONFIG_FILE_PATH,
            "task_id": task_id,
            "log": log,
        }
        exec(code, exec_globals)
        log.info("任务 id=%s 执行完成", task_id)
        return True
    except Exception:
        log.exception("任务 id=%s 执行异常", task_id)
        return False


def schedule_execution(task, executed_ids, lock):
    tid = task.get("id")
    if not tid:
        log.warning("跳过无 id 的任务: %s", task)
        return

    with lock:
        if tid in executed_ids:
            log.debug("任务 id=%s 已执行过，跳过", tid)
            return
        executed_ids.add(tid)

    run_time = parse_task_time(task.get("time"))
    code = task.get("code") or task.get("command")
    if not code:
        log.warning("任务 id=%s 缺少 code/command，跳过", tid)
        return

    if run_time is None:
        log.info("任务 id=%s 未指定执行时间，立即执行", tid)
        execute_code(code, tid)
        mark_executed(tid)
        return

    now = datetime.now()
    delay = (run_time - now).total_seconds()
    if delay <= 0:
        log.info(
            "任务 id=%s 的执行时间(%s)已过期或刚到，立即执行",
            tid,
            run_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        execute_code(code, tid)
        mark_executed(tid)
        return

    log.info(
        "任务 id=%s 将在 %s 执行（约 %.1f 秒后）",
        tid,
        run_time.strftime("%Y-%m-%d %H:%M:%S"),
        delay,
    )

    def _runner():
        remaining = (run_time - datetime.now()).total_seconds()
        if remaining > 0:
            time.sleep(remaining)
        ok = execute_code(code, tid)
        mark_executed(tid)
        if not ok:
            log.warning("任务 id=%s 执行失败，已记录到 %s", tid, LOG_FILE_NAME)

    t = threading.Thread(target=_runner, name="task-" + str(tid), daemon=True)
    t.start()


def process_tasks(tasks, executed_ids, lock):
    if not tasks:
        log.info("本次无任务可处理")
        return
    valid = []
    for t in tasks:
        if isinstance(t, dict):
            valid.append(t)
        else:
            log.warning("忽略非字典任务项: %s", t)
    log.info("本轮共收到 %d 个任务", len(valid))
    for task in valid:
        schedule_execution(task, executed_ids, lock)


def main():
    log.info("Agent 启动，工作目录: %s", BASE_DIR)
    log.info("远程任务地址: %s", TASK_URL)
    log.info("本地任务配置: %s", CONFIG_FILE_PATH)
    log.info("已执行记录: %s", LOG_FILE_PATH)

    executed_ids = load_executed_ids()
    log.info("已加载 %d 条历史执行记录", len(executed_ids))
    lock = threading.Lock()

    local_tasks = load_config_tasks()
    if local_tasks:
        log.info("开始处理本地配置中的任务")
        process_tasks(local_tasks, executed_ids, lock)

    while True:
        remote_tasks = fetch_tasks()
        if remote_tasks is not None:
            process_tasks(remote_tasks, executed_ids, lock)
        log.info("休眠 %d 秒后再次轮询", POLL_INTERVAL_SECONDS)
        try:
            time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            log.info("收到中断信号，退出")
            break


if __name__ == "__main__":
    main()