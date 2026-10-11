from prometheus_client import Counter, Gauge, Histogram

NOTIFICATIONS_CREATED = Counter(
    "notifications_created_total", "Notifications accepted", ["channel", "category"]
)
NOTIFICATIONS_SKIPPED = Counter(
    "notifications_skipped_total", "Notifications skipped by preference", ["channel", "category"]
)
DELIVERY_ATTEMPTS = Counter(
    "delivery_attempts_total", "Delivery attempts", ["channel", "outcome"]
)
DELIVERY_LATENCY = Histogram(
    "delivery_latency_seconds", "Provider send latency", ["channel"]
)
DEAD_LETTERED = Counter("notifications_dead_lettered_total", "Dead lettered", ["channel"])
QUEUE_DEPTH = Gauge("queue_depth", "Ready queue depth")
DELAYED_DEPTH = Gauge("delayed_queue_depth", "Delayed queue depth")
REAPED = Counter("notifications_reaped_total", "Recovered by reaper", ["reason"])
HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram("http_request_latency_seconds", "HTTP latency", ["method", "path"])
