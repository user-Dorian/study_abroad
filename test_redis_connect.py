import redis

# Try connecting without password
try:
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    r.ping()
    print("Redis connected without password")
except Exception as e:
    print(f"No password failed: {e}")

# Try with common passwords
for pwd in ["", "123456", "redis", "root", "admin", "password"]:
    try:
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True, password=pwd if pwd else None)
        r.ping()
        print(f"Redis connected with password: '{pwd}'")
        break
    except Exception as e:
        pass
else:
    print("Could not connect to Redis with any common password")
