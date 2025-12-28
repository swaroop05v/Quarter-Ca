import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
import sys

# Import the refactored analysis function
try:
    from analyze_financials import run_analysis
except ImportError:
    print("Error: Could not import 'run_analysis' from 'analyze_financials.py'.")
    print("Make sure the file exists and has been refactored.")
    sys.exit(1)

# --- Configuration ---
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"xlsx", "pdf"}

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Enable CORS (Cross-Origin Resource Sharing)
# This allows your React app to make requests to this server
CORS(app)


# --- Helper Function ---
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Create the uploads directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


# --- API Endpoint ---
@app.route("/analyze", methods=["POST"])
def analyze_file():
    # 1. Check if a file was sent
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # 2. Check if the file type is allowed and save it
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        try:
            file.save(file_path)
        except Exception as e:
            return jsonify({"error": f"Failed to save file: {e}"}), 500

        result = {}
        file_ext = filename.rsplit(".", 1)[1].lower()

        # --- MODIFIED: Get peer ticker from the form ---
        # Default to 'AAPL' (Apple) if no ticker is provided
        ticker = request.form.get("ticker", "AAPL")

        # 3. Run analysis logic based on file type
        if file_ext == "xlsx":
            # This file type can be analyzed by your script
            # --- MODIFIED: Pass ticker to run_analysis ---
            result = run_analysis(file_path, ticker)

        elif file_ext == "pdf":
            # PDF upload is allowed, but we return a specific message
            result = {
                "message": "PDF file uploaded successfully.",
                "filename": filename,
                "overall_score": 0,
                "ratios": {},
                "sub_scores": {},
                "trends": [],
                "ai_insights": "PDF files are not supported for financial analysis. Please upload an .xlsx file.",
                "benchmarks": {},  # Add empty benchmark for consistency
            }

        # 4. Clean up the uploaded file
        if os.path.exists(file_path):
            os.remove(file_path)

        # 5. Return the JSON result
        if "error" in result:
            return jsonify(result), 500

        return jsonify(result)

    else:
        return (
            jsonify({"error": "File type not allowed. Please upload .xlsx or .pdf"}),
            400,
        )


# --- Run the Server ---
if __name__ == "__main__":
    print("Starting Flask server on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
