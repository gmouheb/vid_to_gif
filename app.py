import os
import time
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash, session
from moviepy import VideoFileClip
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'gifs'
ALLOWED_EXTENSIONS = {'webm', 'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv', 'mpeg'}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB limit

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For flashing messages
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(os.path.join('static', 'gifs'), exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def clean_old_files(directory, max_age_hours=24):
    """Remove files older than max_age_hours from the specified directory"""
    current_time = time.time()
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        # If file is older than max_age_hours, delete it
        if os.path.isfile(file_path) and (current_time - os.path.getmtime(file_path)) > max_age_hours * 3600:
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error removing {file_path}: {e}")


def delete_file_safely(file_path):
    """Delete a file if it exists and return success status"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")
        return False


@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # Clean old files first
        clean_old_files(app.config['UPLOAD_FOLDER'])
        clean_old_files(app.config['OUTPUT_FOLDER'])
        clean_old_files(os.path.join('static', 'gifs'))

        # Check if the post request has the file part
        if 'video' not in request.files:
            flash('No file part')
            return redirect(request.url)

        file = request.files['video']

        # If user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            # Get conversion parameters
            fps = int(request.form.get('fps', 10))
            width = request.form.get('width', '')
            if width and width.isdigit():
                width = int(width)
            else:
                width = None

            # Handle start and end time
            start_time = request.form.get('start_time', '')
            end_time = request.form.get('end_time', '')

            try:
                if start_time:
                    start_time = float(start_time)
                else:
                    start_time = None

                if end_time:
                    end_time = float(end_time)
                else:
                    end_time = None
            except ValueError:
                flash('Invalid time format. Please use seconds (e.g., 10.5)')
                return redirect(request.url)

            # Save the uploaded file
            timestamp = int(time.time())
            filename = f"{timestamp}_{secure_filename(file.filename)}"
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(input_path)

            # Create output filename
            gif_filename = f"{os.path.splitext(filename)[0]}.gif"
            gif_path = os.path.join(app.config['OUTPUT_FOLDER'], gif_filename)

            # Also save a copy to static folder for preview
            static_gif_path = os.path.join('static', 'gifs', gif_filename)

            try:
                # Load the video file
                clip = VideoFileClip(input_path)

                # Apply time trimming if specified
                if start_time is not None or end_time is not None:
                    clip = clip.subclip(start_time, end_time)

                # Resize if width is specified
                if width:
                    clip = clip.resize(width=width)

                # Write the GIF file with the specified fps
                clip.write_gif(gif_path, fps=fps)

                # Copy to static folder for preview
                import shutil
                shutil.copy2(gif_path, static_gif_path)

                # Store filename in session for display and later cleanup
                session['gif_filename'] = gif_filename
                session['original_filename'] = file.filename
                session['gif_size'] = os.path.getsize(gif_path) / (1024 * 1024)  # Size in MB
                session['input_path'] = input_path
                session['gif_path'] = gif_path
                session['static_gif_path'] = static_gif_path

                return redirect(url_for('result'))

            except Exception as e:
                # Clean up the input file in case of error
                delete_file_safely(input_path)
                flash(f"Conversion failed: {str(e)}")
                return redirect(request.url)
        else:
            flash(f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}")
            return redirect(request.url)

    return render_template('upload.html')


@app.route('/result')
def result():
    if 'gif_filename' not in session:
        return redirect(url_for('upload_file'))

    gif_filename = session['gif_filename']
    original_filename = session.get('original_filename', 'unknown')
    gif_size = session.get('gif_size', 0)

    return render_template(
        'result.html',
        gif_filename=gif_filename,
        original_filename=original_filename,
        gif_size=round(gif_size, 2)
    )


# @app.route('/gifs/<filename>')
# def download_file(filename):
#     """Send the file for download and schedule it for deletion"""
#     # Get paths from session for deletion after download
#     input_path = session.get('input_path')
#     gif_path = session.get('gif_path')
#     static_gif_path = session.get('static_gif_path')
#
#     # Send the file first
#     response = send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)
#
#     # Then delete the files
#     try:
#         # Delete all associated files
#         if input_path:
#             delete_file_safely(input_path)
#
#         if gif_path:
#             delete_file_safely(gif_path)
#
#         if static_gif_path:
#             delete_file_safely(static_gif_path)
#
#         # Clear the session data
#         session.pop('gif_filename', None)
#         session.pop('original_filename', None)
#         session.pop('gif_size', None)
#         session.pop('input_path', None)
#         session.pop('gif_path', None)
#         session.pop('static_gif_path', None)
#
#     except Exception as e:
#         print(f"Error during file cleanup: {e}")
#
#     return response

@app.route('/gifs/<filename>')
def download_file(filename):
    """Send the file for download and delete uploaded and generated files"""

    # Send the file first
    response = send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)

    try:
        # Get paths from session for deletion
        input_path = session.get('input_path')
        gif_path = session.get('gif_path')
        static_gif_path = session.get('static_gif_path')

        # Delete session-stored paths if they exist
        if input_path:
            delete_file_safely(input_path)

        if gif_path:
            delete_file_safely(gif_path)

        if static_gif_path:
            delete_file_safely(static_gif_path)

        # Fallback: explicitly build and delete from filename
        delete_file_safely(os.path.join(app.config['OUTPUT_FOLDER'], filename))
        delete_file_safely(os.path.join('static', 'gifs', filename))

        # Try to infer and delete the input video from the timestamp in filename
        timestamp = filename.split('_')[0]
        for f in os.listdir(app.config['UPLOAD_FOLDER']):
            if f.startswith(timestamp):
                delete_file_safely(os.path.join(app.config['UPLOAD_FOLDER'], f))

        # Clear session data
        session.pop('gif_filename', None)
        session.pop('original_filename', None)
        session.pop('gif_size', None)
        session.pop('input_path', None)
        session.pop('gif_path', None)
        session.pop('static_gif_path', None)

    except Exception as e:
        print(f"Error during file cleanup: {e}")

    return response



@app.route('/preview/<filename>')
def preview_file(filename):
    return send_from_directory(os.path.join('static', 'gifs'), filename)


@app.errorhandler(413)
def request_entity_too_large(error):
    flash(f"File too large. Maximum size is {MAX_CONTENT_LENGTH / (1024 * 1024)}MB")
    return redirect(url_for('upload_file')), 413


if __name__ == '__main__':
    app.run(debug=True)