from flask import Flask, jsonify, send_file
import os
from sqlalchemy import create_engine, text

_engine = None

def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    db_url = os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("Missing DB_URL (or DATABASE_URL) environment variable.")
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    _engine = create_engine(db_url, pool_pre_ping=True)
    return _engine


def create_app():
    app = Flask(__name__)

    # ---- 基本健康測試 ----
    @app.get("/", endpoint="health")
    def health():
        return "<p>Server working!</p>"

    @app.get("/img", endpoint="show_img")
    def show_img():
        return send_file("amygdala.gif", mimetype="image/gif")

    # ---- 單一 term 查詢 ----
    @app.get("/terms/<term>/studies", endpoint="terms_studies")
    def get_studies_by_term(term):
        import pandas as pd
        try:
            df = pd.read_parquet("annotations.parquet")
            meta = pd.read_parquet("metadata.parquet")

            col = f"terms_abstract_tfidf__{term}"
            if col not in df.columns:
                return jsonify({"error": f"term '{term}' not found"}), 404

            studies = df.loc[df[col] > 0, ["study_id", col]]
            merged = pd.merge(studies, meta, on="study_id", how="left")

            return jsonify(merged.head(10).to_dict(orient="records"))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- 單一座標查詢 ----
    @app.get("/locations/<coords>/studies", endpoint="locations_studies")
    def get_studies_by_coordinates(coords):
        import pandas as pd
        try:
            x, y, z = map(float, coords.split("_"))
            coord = pd.read_parquet("coordinates.parquet")
            meta = pd.read_parquet("metadata.parquet")

            # 找出與輸入座標距離最接近的研究（可自行調整距離閾值）
            filtered = coord[(abs(coord["x"] - x) < 5) &
                             (abs(coord["y"] - y) < 5) &
                             (abs(coord["z"] - z) < 5)]

            merged = pd.merge(filtered, meta, on=["study_id", "contrast_id"], how="left")
            return jsonify(merged.head(10).to_dict(orient="records"))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- Dissociate by terms ----
    @app.get("/dissociate/terms/<term_a>/<term_b>", endpoint="dissociate_terms")
    def dissociate_terms(term_a, term_b):
        import pandas as pd
        try:
            df = pd.read_parquet("annotations.parquet")
            meta = pd.read_parquet("metadata.parquet")

            col_a = f"terms_abstract_tfidf__{term_a}"
            col_b = f"terms_abstract_tfidf__{term_b}"

            if col_a not in df.columns or col_b not in df.columns:
                return jsonify({"error": "term not found"}), 404

            filtered = df[(df[col_a] > 0) & (df[col_b] == 0)]
            merged = pd.merge(filtered[["study_id", col_a]], meta, on="study_id", how="left")

            return jsonify(merged.head(10).to_dict(orient="records"))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- Dissociate by locations ----
    @app.get("/dissociate/locations/<coords_a>/<coords_b>", endpoint="dissociate_locations")
    def dissociate_locations(coords_a, coords_b):
        import pandas as pd
        try:
            x1, y1, z1 = map(float, coords_a.split("_"))
            x2, y2, z2 = map(float, coords_b.split("_"))
            coord = pd.read_parquet("coordinates.parquet")
            meta = pd.read_parquet("metadata.parquet")

            # 找出接近 coords_a 但不接近 coords_b 的研究
            close_a = coord[(abs(coord["x"] - x1) < 5) &
                            (abs(coord["y"] - y1) < 5) &
                            (abs(coord["z"] - z1) < 5)]
            close_b = coord[(abs(coord["x"] - x2) < 5) &
                            (abs(coord["y"] - y2) < 5) &
                            (abs(coord["z"] - z2) < 5)]

            only_a = close_a[~close_a["study_id"].isin(close_b["study_id"])]
            merged = pd.merge(only_a, meta, on=["study_id", "contrast_id"], how="left")

            return jsonify(merged.head(10).to_dict(orient="records"))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- 讀取 annotations.parquet ----
    @app.get("/read_annotations", endpoint="read_annotations")
    def read_annotations():
        import pandas as pd
        try:
            df = pd.read_parquet("annotations.parquet")
            sample = df.head(5).to_dict(orient="records")
            return jsonify({
                "rows": len(df),
                "columns": list(df.columns),
                "sample": sample
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- 讀取 metadata.parquet ----
    @app.get("/read_metadata", endpoint="read_metadata")
    def read_metadata():
        import pandas as pd
        try:
            df = pd.read_parquet("metadata.parquet")
            sample = df.head(5).to_dict(orient="records")
            return jsonify({
                "rows": len(df),
                "columns": list(df.columns),
                "sample": sample
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- 讀取 coordinates.parquet ----
    @app.get("/read_coordinates", endpoint="read_coordinates")
    def read_coordinates():
        import pandas as pd
        try:
            df = pd.read_parquet("coordinates.parquet")
            sample = df.head(5).to_dict(orient="records")
            return jsonify({
                "rows": len(df),
                "columns": list(df.columns),
                "sample": sample
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- 合併 coordinates + metadata ----
    @app.get("/merge_coordinates", endpoint="merge_coordinates")
    def merge_coordinates():
        import pandas as pd
        try:
            coord = pd.read_parquet("coordinates.parquet")
            meta = pd.read_parquet("metadata.parquet")
            merged = coord.merge(meta, on=["study_id", "contrast_id"], how="left")
            sample = merged.head(5).to_dict(orient="records")
            return jsonify({
                "rows": len(merged),
                "columns": list(merged.columns),
                "sample": sample
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- 資料庫測試 ----
    @app.get("/test_db", endpoint="test_db")
    def test_db():
        eng = get_engine()
        payload = {"ok": False, "dialect": eng.dialect.name}

        try:
            with eng.begin() as conn:
                conn.execute(text("SET search_path TO ns, public;"))
                payload["version"] = conn.exec_driver_sql("SELECT version()").scalar()
                payload["ok"] = True
                return jsonify(payload), 200
        except Exception as e:
            payload["error"] = str(e)
            return jsonify(payload), 500

    return app


app = create_app()
