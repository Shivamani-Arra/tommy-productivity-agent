from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()


def _env_value(name):
    value = os.getenv(name, "")
    return value.strip().strip('"').strip("'")


def _required_env(name):
    value = _env_value(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


supabase_url = _required_env("SUPABASE_URL")
supabase_key = _required_env("SUPABASE_KEY")

if not supabase_url.startswith(("https://", "http://")):
    raise RuntimeError(
        "SUPABASE_URL must be only the project URL, for example "
        "https://your-project.supabase.co. Do not paste SUPABASE_URL= before it."
    )

supabase = create_client(
    supabase_url,
    supabase_key
)
