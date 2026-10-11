local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local data = redis.call("HMGET", key, "tokens", "ts")
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil then
  tokens = capacity
  ts = now_ms
end

local elapsed = math.max(0, now_ms - ts) / 1000
tokens = math.min(capacity, tokens + elapsed * refill_per_sec)

local allowed = 0
local retry_ms = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  retry_ms = math.ceil(((requested - tokens) / refill_per_sec) * 1000)
end

redis.call("HSET", key, "tokens", tostring(tokens), "ts", tostring(now_ms))
redis.call("PEXPIRE", key, math.ceil((capacity / refill_per_sec) * 1000) + 1000)

return {allowed, math.floor(tokens), retry_ms}
