import os
import zipfile
from io import BytesIO
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect,
    url_for, send_from_directory, flash,
    jsonify, session, send_file
)
from werkzeug.utils import secure_filename
import qrcode
from PIL import Image
import cv2
import segno

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ==============================
# FOLDER SETUP
# ==============================

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr_codes")
LOGO_FOLDER = os.path.join(BASE_DIR, "static", "logos")

for folder in [UPLOAD_FOLDER, QR_FOLDER, LOGO_FOLDER]:
    os.makedirs(folder, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}

qr_history = []
total_scans = 0


# ==============================
# SESSION INIT
# ==============================

@app.before_request
def init_session():
    if "scan_history" not in session:
        session["scan_history"] = []


# ==============================
# HELPERS
# ==============================

def allowed_file(filename):
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def smart_detect(data):
    if not data:
        return "text"

    data = data.strip()

    if data.startswith("mailto:"):
        return "email"

    if data.startswith("tel:"):
        return "phone"

    if "youtube.com" in data or "youtu.be" in data:
        return "youtube"

    if "wa.me" in data or "whatsapp.com" in data:
        return "whatsapp"

    if "maps.google" in data:
        return "maps"

    if data.lower().endswith((".png", ".jpg", ".jpeg")):
        return "image"

    if data.lower().endswith(".pdf"):
        return "pdf"

    if data.startswith("http"):
        return "url"

    return "text"


# ==============================
# QR GENERATION
# ==============================

def generate_qr(data, fill_color, back_color, logo_file=None):
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(
        fill_color=fill_color,
        back_color=back_color
    ).convert("RGB")

    # Add logo in center
    if logo_file:
        logo = Image.open(logo_file)
        logo_size = (img.size[0] // 4, img.size[1] // 4)
        logo = logo.resize(logo_size)
        pos = (
            (img.size[0] - logo_size[0]) // 2,
            (img.size[1] - logo_size[1]) // 2
        )
        img.paste(logo, pos)

    filename = datetime.now().strftime("%Y%m%d%H%M%S") + ".png"
    filepath = os.path.join(QR_FOLDER, filename)
    img.save(filepath)

    # SVG version
    svg_name = filename.replace(".png", ".svg")
    seg = segno.make(data)
    seg.save(os.path.join(QR_FOLDER, svg_name))

    qr_history.insert(0, {
        "filename": filename,
        "data": data,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

    return filename


# ==============================
# ROUTES
# ==============================

@app.route("/", methods=["GET", "POST"])
def index():
    qr_image = None

    if request.method == "POST":
        qr_type = request.form.get("qr_type")
        fill_color = request.form.get("fill_color", "#000000")
        back_color = request.form.get("back_color", "#ffffff")

        data = None

        if qr_type == "text":
            data = request.form.get("text")

        elif qr_type == "website":
            website = request.form.get("website")
            if website and not website.startswith("http"):
                website = "https://" + website
            data = website

        elif qr_type == "email":
            email = request.form.get("email")
            data = f"mailto:{email}" if email else None

        elif qr_type == "phone":
            phone = request.form.get("phone")
            data = f"tel:{phone}" if phone else None

        elif qr_type == "wifi":
            ssid = request.form.get("ssid")
            password = request.form.get("password")
            if ssid and password:
                data = f"WIFI:T:WPA;S:{ssid};P:{password};;"

        elif qr_type == "vcard":
            name = request.form.get("name")
            phone = request.form.get("vphone")
            email = request.form.get("vemail")
            if name:
                data = f"""
BEGIN:VCARD
VERSION:3.0
FN:{name}
TEL:{phone}
EMAIL:{email}
END:VCARD
"""

        elif qr_type == "file":
            file = request.files.get("file")
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                path = os.path.join(UPLOAD_FOLDER, filename)
                file.save(path)
                data = request.host_url + "static/uploads/" + filename

        # Logo upload
        logo = request.files.get("logo")
        logo_path = None

        if logo and allowed_file(logo.filename):
            logo_filename = secure_filename(logo.filename)
            logo_path = os.path.join(LOGO_FOLDER, logo_filename)
            logo.save(logo_path)

        if data:
            qr_image = generate_qr(
                data, fill_color, back_color, logo_path
            )
        else:
            flash("Invalid input.")

    return render_template("index.html", qr_image=qr_image)


# ==============================
# SCAN PAGE
# ==============================

@app.route("/scan", methods=["GET", "POST"])
def scan():
    global total_scans
    result = None
    result_type = None

    if request.method == "POST":
        file = request.files.get("scan_file")
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)

            img = cv2.imread(filepath)
            detector = cv2.QRCodeDetector()
            data, bbox, _ = detector.detectAndDecode(img)

            if data:
                result = data
                result_type = smart_detect(data)
                total_scans += 1

                history = session["scan_history"]
                history.insert(0, {
                    "data": data,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "type": result_type
                })
                session["scan_history"] = history

            else:
                result = "No QR detected"
                result_type = "text"

    return render_template(
        "scan.html",
        result=result,
        result_type=result_type
    )


# ==============================
# CAMERA SCAN API
# ==============================

@app.route("/camera_scan", methods=["POST"])
def camera_scan():
    global total_scans

    data = request.json.get("data")
    result_type = smart_detect(data)

    total_scans += 1

    history = session["scan_history"]
    history.insert(0, {
        "data": data,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": result_type
    })
    session["scan_history"] = history

    return jsonify({
        "data": data,
        "type": result_type
    })


# ==============================
# DASHBOARD
# ==============================

@app.route("/dashboard")
def dashboard():
    return render_template(
        "dashboard.html",
        history=qr_history,
        total_qr=len(qr_history),
        total_scans=total_scans,
        scan_history=session["scan_history"]
    )


# ==============================
# DOWNLOADS
# ==============================

@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(
        QR_FOLDER,
        filename,
        as_attachment=True
    )


@app.route("/download_zip/<filename>")
def download_zip(filename):
    png_path = os.path.join(QR_FOLDER, filename)
    svg_path = os.path.join(
        QR_FOLDER,
        filename.replace(".png", ".svg")
    )

    memory_file = BytesIO()

    with zipfile.ZipFile(memory_file, "w") as zf:
        zf.write(png_path, arcname=filename)
        zf.write(
            svg_path,
            arcname=filename.replace(".png", ".svg")
        )

    memory_file.seek(0)

    return send_file(
        memory_file,
        download_name=filename.replace(".png", ".zip"),
        as_attachment=True
    )


# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    app.run(debug=True)
