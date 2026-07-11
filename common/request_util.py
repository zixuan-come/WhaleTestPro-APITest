import httpx


class HttpUtil:
    def __init__(self, base_url, headers=None, timeout=10):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout

    def request(self, method, path, **kwargs):
        url = self.base_url + path
        headers = self.headers.copy()
        headers.update(kwargs.pop("headers", {}) or {})

        return httpx.request(
            method=method,
            url=url,
            headers=headers,
            timeout=self.timeout,
            **kwargs
        )

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)





