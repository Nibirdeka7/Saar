from app.config import settings

config = settings()


print("Database URL:", "Loaded" if config.database_url else "Missing")
print("AWS Access Key:", "Loaded" if config.aws_access_key_id else "Missing")
print("AWS Secret Key:", "Loaded" if config.aws_secret_access_key else "Missing")

