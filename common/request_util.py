import logging
import time

import httpx

# 统一的 HTTP 日志器。handler 由 conftest 挂到文件(logs/http.log),
# 这里只负责产出记录:每条请求打一行 method/path/状态码/耗时,失败排查用。
log = logging.getLogger("whale.http")


class RequestUtil:
    def __init__(self, base_url, headers=None, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout

    def request(self, method, path, **kwargs):
        url = self.base_url + path
        headers = self.headers.copy()
        headers.update(kwargs.pop("headers", {}) or {})

        start = time.perf_counter()
        try:
            resp = httpx.request(
                method=method,
                url=url,
                headers=headers,
                timeout=self.timeout,
                **kwargs
            )
        except Exception as exc:
            cost = (time.perf_counter() - start) * 1000
            log.warning("%s %s -> 异常 %s (%.0fms)", method, url, exc, cost)
            raise
        cost = (time.perf_counter() - start) * 1000
        log.info("%s %s -> %s (%.0fms)", method, url, resp.status_code, cost)
        return resp

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)

    def patch(self, path, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)





