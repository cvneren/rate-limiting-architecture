-- Generic Cell Rate Algorithm (GCRA) implementation in Lua
-- KEYS[1]: The rate limit key (e.g., rate:limit:{client_id})
-- ARGV[1]: Emission Interval (T) in seconds (float)
-- ARGV[2]: Burst Tolerance (tau) in seconds (float)

local key = KEYS[1]
local t = tonumber(ARGV[1])
local tau = tonumber(ARGV[2])

-- Get current time from Redis to avoid clock drift
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + (tonumber(redis_time[2]) / 1000000)

-- Get current Theoretical Arrival Time (TAT)
local tat = tonumber(redis.call('GET', key))

if not tat then
    -- Initialization: first request
    tat = now
end

-- Check if request is compliant
local new_tat
local is_allowed = 0
local remaining = 0
local retry_after = 0

if now < (tat - tau) then
    -- Non-compliant: request arrived too soon
    is_allowed = 0
    new_tat = tat
    retry_after = tat - tau - now
else
    -- Compliant
    is_allowed = 1
    new_tat = math.max(now, tat) + t
    
    -- Update Redis with new TAT
    -- TTL should be enough to cover the window plus some buffer
    local ttl = math.ceil(new_tat - now + tau)
    redis.call('SET', key, new_tat, 'EX', ttl)
end

-- Calculate remaining burst capacity (roughly)
-- Remaining = (tau - (tat - now)) / t
local remaining_burst = math.floor((tau - math.max(0, new_tat - now - t)) / t)

-- Return: is_allowed, remaining, retry_after
return {is_allowed, remaining_burst, retry_after}
