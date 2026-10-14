import os
import ast
import glob
import torch
import numpy as np
import pandas as pd
from PIL import Image
import torch.nn.functional as F
from transformers import CLIPProcessor, CLIPModel
from sklearn.metrics.pairwise import cosine_similarity

# ---------------------------------------------------------
# 1. LOAD EMBEDDINGS & METADATA FROM CSV FILES
# ---------------------------------------------------------
print("Loading pre-computed embeddings from CSV...")

if not os.path.exists("train_embeddings.csv") or not os.path.exists("locations_info.csv"):
    print("Error: 'train_embeddings.csv' or 'locations_info.csv' not found! Make sure they are in the current working directory.")
else:
    df_embeddings = pd.read_csv("train_embeddings.csv")
    df_locations = pd.read_csv("locations_info.csv")

    # Convert string representation of list back to numpy arrays
    df_embeddings["embedding_vec"] = df_embeddings["embedding"].apply(lambda x: np.array(ast.literal_eval(x)))

    # Map point ID to location name
    point_id_to_name = dict(zip(df_locations["id"], df_locations["name"]))

    # Stack all training vectors into a single matrix (Shape: N_train x 512)
    train_matrix = np.vstack(df_embeddings["embedding_vec"].values)

    print(f"Loaded {len(df_embeddings)} reference embeddings across {len(df_locations)} locations.")

    # ---------------------------------------------------------
    # 2. SETUP MODEL FOR QUERY IMAGES ONLY
    # ---------------------------------------------------------
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_id = "openai/clip-vit-base-patch32"

    print(f"\nLoading CLIP model '{model_id}' onto {device}...")
    model = CLIPModel.from_pretrained(model_id).to(device)
    processor = CLIPProcessor.from_pretrained(model_id)

    def get_image_embedding(img_path):
        img = Image.open(img_path).convert("RGB")
        inputs = processor(images=img, return_tensors="pt").to(device)
        
        with torch.no_grad():
            outputs = model.get_image_features(**inputs)
        
        if hasattr(outputs, "pooler_output"):
            image_features = outputs.pooler_output
        elif hasattr(outputs, "image_embeds"):
            image_features = outputs.image_embeds
        else:
            image_features = outputs

        return F.normalize(image_features, dim=-1).cpu().numpy().squeeze(0)

    def get_all_images_in_folder(folder_path):
        extensions = ('*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG')
        files = []
        for ext in extensions:
            files.extend(glob.glob(os.path.join(folder_path, "**", ext), recursive=True))
        return sorted(files)

    # ---------------------------------------------------------
    # 3. RUN PREDICTIONS ON VALIDATION FOLDER
    # ---------------------------------------------------------
    VAL_DIR = "dataset/validation"
    val_image_paths = get_all_images_in_folder(VAL_DIR)

    if not val_image_paths:
        print("\nError: No validation images found in 'dataset/validation'.")
    else:
        print("\n" + "="*60)
        print("             RUNNING FAST CSV-BASED PREDICTIONS             ")
        print("="*60)

        results = []

        for val_path in val_image_paths:
            val_filename = os.path.basename(val_path)
            
            # Embed only the query validation image
            val_emb = get_image_embedding(val_path).reshape(1, -1)
            
            # Compute cosine similarity between query and pre-computed matrix
            similarities = cosine_similarity(val_emb, train_matrix)[0]
            
            # Get best match
            best_idx = np.argmax(similarities)
            highest_sim = similarities[best_idx]
            
            matched_row = df_embeddings.iloc[best_idx]
            predicted_point_id = matched_row["id_point"]
            predicted_location = point_id_to_name.get(predicted_point_id, "Unknown")
            matched_ref_image = matched_row["image_name"]

            results.append({
                "Validation Image": val_filename,
                "Predicted Point ID": predicted_point_id,
                "Predicted Location": predicted_location,
                "Max Similarity": f"{highest_sim * 100:.2f}%",
                "Matched CSV Reference": matched_ref_image
            })
            
            print(f"\nImage: '{val_filename}'")
            print(f"  |-- Predicted Point ID : {predicted_point_id} ({predicted_location.upper()})")
            print(f"  |-- Similarity Score   : {highest_sim * 100:.2f}% (matched CSV row ID {matched_row['id']}: '{matched_ref_image}')")

        # ---------------------------------------------------------
        # 4. DISPLAY SUMMARY TABLE
        # ---------------------------------------------------------
        print("\n" + "="*60)
        print("                     SUMMARY TABLE                          ")
        print("="*60)

        df_results = pd.DataFrame(results)
        print(df_results.to_string(index=False))