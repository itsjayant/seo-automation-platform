-- Sliding Window Rate Limiter with distributed coordination
-- Args: KEYS[1] = rate limit key, ARGV[1] = window_seconds, ARGV[2] = max_requests, ARGV[3] = current_time_ms
-- Returns: {allowed (0/1), current_count, remaining_quota, reset_time_ms}

local key = KEYS[1]
local window_seconds = tonumber(ARGV[1])
local max_requests = tonumber(ARGV[2]) 
local current_time_ms = tonumber(ARGV[3])

-- Calculate window boundaries
local window_ms = window_seconds * 1000
local window_start = current_time_ms - window_ms
local window_end = current_time_ms

-- Remove expired entries from sorted set
redis.call('ZREMRANGEBYSCORE', key, 0, window_start)

-- Count current requests in window
local current_count = redis.call('ZCARD', key)

if current_count < max_requests then
    -- Allow request and add to window
    redis.call('ZADD', key, current_time_ms, current_time_ms)
    
    -- Set expiration for cleanup (2x window to handle clock skew)
    redis.call('EXPIRE', key, window_seconds * 2)
    
    local remaining = max_requests - current_count - 1
    return {1, current_count + 1, remaining, window_end}
else
    -- Request denied - calculate next reset time
    local oldest_request = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local reset_time = window_end
    if oldest_request[2] then
        reset_time = tonumber(oldest_request[2]) + window_ms
    end
    
    return {0, current_count, 0, reset_time}
end