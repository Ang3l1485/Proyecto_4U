import os

# --- Database ---
DB_HOST   = os.environ["DB_HOST"]
DB_PORT   = int(os.environ.get("DB_PORT", "5432"))
DB_USER   = os.environ.get("DB_USER", "postgres")
DB_NAME   = os.environ.get("DB_NAME", "postgres")
DB_REGION = os.environ.get("DB_REGION", "us-east-2")

# Table that holds the pre-computed reference embeddings
EMBEDDINGS_TABLE = os.environ.get("EMBEDDINGS_TABLE", "train_embeddings")

# Table that maps point IDs to human-readable location names
LOCATIONS_TABLE  = os.environ.get("LOCATIONS_TABLE", "locations_info")

# --- S3 input: images to classify ---
INPUT_BUCKET = os.environ.get("INPUT_BUCKET", "4uproject-eafit")
INPUT_PREFIX = os.environ.get("INPUT_PREFIX", "testing/")   # folder with .png files

# --- S3 output: where the summary CSV is written ---
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "4uproject-eafit")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "output/")

# --- CLIP model (must match the model used to generate the stored embeddings) ---
CLIP_MODEL_ID = os.environ.get("CLIP_MODEL_ID", "openai/clip-vit-base-patch32")
