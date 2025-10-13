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

    @app.get("/", endpoint="health")
    def health():
        return "<p>Server working!</p>"

    @app.get("/img", endpoint="show_img")
    def show_img():
        return send_file("amygdala.gif", mimetype="image/gif")

    # ---- 查單一 term ----
    @app.get("/terms/<term>/studies", endpoint="terms_studies")
    def get_studies_by_term(term):
        import pandas as pd
        db_url = os.getenv("DB_URL")
        try:
            if db_url:
                eng = get_engine()
                with eng.begin() as conn:
                    query = text("""
                        SELECT a.study_id, a.term, a.weight,
                               m.title, m.authors, m.journal, m.year
                        FROM ns.annotations_terms a
                        JOIN ns.metadata m USING (study_id)
                        WHERE a.term ILIKE :term
                        ORDER BY a.weight DESC
                        LIMIT 10;
                    """)
                    rows = conn.execute(query, {"term": f"%{term}%"}).mappings().all()
                return jsonify([dict(r) for r in rows])
            else:
                df = pd.read_parquet("annotations.parquet")
                meta = pd.read_parquet("metadata.parquet")
                matching_cols = [c for c in df.columns if term.lower() in c.lower()]
                if not matching_cols:
                    return jsonify({"error": f"term '{term}' not found"}), 404
                merged = None
                for col in matching_cols:
                    subset = df.loc[df[col] > 0, ["study_id", col]].rename(columns={col: "weight"})
                    merged_part = pd.merge(subset, meta, on="study_id", how="left")
                    merged = pd.concat([merged, merged_part]) if merged is not None else merged_part
                return jsonify(merged.head(10).to_dict(orient="records"))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- 查座標附近研究 ----
    @app.get("/locations/<coords>/studies", endpoint="locations_studies")
    def get_studies_by_coordinates(coords):
        import pandas as pd
        db_url = os.getenv("DB_URL")
        try:
            x, y, z = map(float, coords.split("_"))
            if db_url:
                eng = get_engine()
                with eng.begin() as conn:
                    query = text("""
                        SELECT c.study_id, ST_X(c.geom) AS x, ST_Y(c.geom) AS y, ST_Z(c.geom) AS z,
                               m.title, m.authors, m.journal, m.year
                        FROM ns.coordinates c
                        JOIN ns.metadata m USING (study_id)
                        WHERE ST_Distance(c.geom, ST_SetSRID(ST_MakePoint(:x, :y, :z), 4326)) < 5
                        LIMIT 10;
                    """)
                    rows = conn.execute(query, {"x": x, "y": y, "z": z}).mappings().all()
                return jsonify([dict(r) for r in rows])
            else:
                coord = pd.read_parquet("coordinates.parquet")
                meta = pd.read_parquet("metadata.parquet")
                filtered = coord[(abs(coord["x"] - x) < 5) &
                                 (abs(coord["y"] - y) < 5) &
                                 (abs(coord["z"] - z) < 5)]
                merged = pd.merge(filtered, meta, on=["study_id", "contrast_id"], how="left")
                return jsonify(merged.head(10).to_dict(orient="records"))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ---- Dissociate by locations ----
    @app.get("/dissociate/locations/<coords_a>/<coords_b>", endpoint="dissociate_locations")
    def dissociate_locations(coords_a, coords_b):
        import pandas as pd
        db_url = os.getenv("DB_URL")
        try:
            x1, y1, z1 = map(float, coords_a.split("_"))
            x2, y2, z2 = map(float, coords_b.split("_"))
            if db_url:
                eng = get_engine()
                with eng.begin() as conn:
                    query = text("""
                        SELECT c.study_id, ST_X(c.geom) AS x, ST_Y(c.geom) AS y, ST_Z(c.geom) AS z,
                               m.title, m.authors, m.journal, m.year
                        FROM ns.coordinates c
                        JOIN ns.metadata m USING (study_id)
                        WHERE ST_Distance(c.geom, ST_SetSRID(ST_MakePoint(:x1, :y1, :z1), 4326)) < 5
                          AND c.study_id NOT IN (
                              SELECT study_id FROM ns.coordinates
                              WHERE ST_Distance(geom, ST_SetSRID(ST_MakePoint(:x2, :y2, :z2), 4326)) < 5
                          )
                        LIMIT 10;
                    """)
                    rows = conn.execute(query, {
                        "x1": x1, "y1": y1, "z1": z1,
                        "x2": x2, "y2": y2, "z2": z2
                    }).mappings().all()
                return jsonify([dict(r) for r in rows])
            else:
                coord = pd.read_parquet("coordinates.parquet")
                meta = pd.read_parquet("metadata.parquet")
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

    # ---- 資料庫測試 ----
    @app.get("/test_db", endpoint="test_db")
    def test_db():
        db_url = os.getenv("DB_URL")
        if not db_url:
            return jsonify({"ok": False, "error": "No DB_URL found"}), 400
        eng = get_engine()
        payload = {"ok": False, "dialect": eng.dialect.name}
        try:
            with eng.begin() as conn:
                conn.execute(text("SET search_path TO ns, public;"))
                payload["version"] = conn.exec_driver_sql("SELECT version()").scalar()
                payload["coordinates_count"] = conn.execute(
                    text("SELECT COUNT(*) FROM ns.coordinates")
                ).scalar()
                payload["metadata_count"] = conn.execute(
                    text("SELECT COUNT(*) FROM ns.metadata")
                ).scalar()
                payload["annotations_terms_count"] = conn.execute(
                    text("SELECT COUNT(*) FROM ns.annotations_terms")
                ).scalar()
            payload["ok"] = True
            return jsonify(payload), 200
        except Exception as e:
            payload["error"] = str(e)
            return jsonify(payload), 500

    return app


app = create_app()
