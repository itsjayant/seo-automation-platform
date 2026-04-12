-- Token Bucket Rate Limiter with burst capacity
-- Args: KEYS[1] = bucket key, ARGV[1] = capacity, ARGV[2] = refill_rate, ARGV[3] = current_time_ms, ARGV[4] = tokens_requested
-- Returns: {allowed (0/1), tokens_available, refill_time_ms}

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])  -- tokens per second
local current_time_ms = tonumber(ARGV[3])
local tokens_requested = tonumber(ARGV[4]) or 1

-- Get current bucket state
local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1]) or capacity
local last_refill = tonumber(bucket[2]) or current_time_ms

-- Calculate tokens to add since last refill
local time_passed = math.max(0, current_time_ms - last_refill) / 1000
local tokens_to_add = math.floor(time_passed * refill_rate)
local new_tokens = math.min(capacity, tokens + tokens_to_add)

-- Calculate next refill time
local next_refill = current_time_ms + (1000 / refill_rate)

if new_tokens >= tokens_requested then
    -- Allow request and consume tokens
    local remaining_tokens = new_tokens - tokens_requested
    
    redis.call('HMSET', key, 
        'tokens', remaining_tokens,
        'last_refill', current_time_ms)
    redis.call('EXPIRE', key, math.ceil(capacity / refill_rate) + 60)
    
    return {1, remaining_tokens, next_refill}
else
    -- Request denied - update bucket state but don't consume
    redis.call('HMSET', key,
        'tokens', new_tokens,
        'last_refill', current_time_ms)
    redis.call('EXPIRE', key, math.ceil(capacity / refill_rate) + 60)
    
    -- Calculate when enough tokens will be available
    local tokens_needed = tokens_requested - new_tokens
    local wait_time_ms = math.ceil(tokens_needed / refill_rate * 1000)
    local available_time = current_time_ms + wait_time_ms
    
    return {0, new_tokens, available_time}
end