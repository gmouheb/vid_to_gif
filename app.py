import os
import time
import tempfile
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, flash, session
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


def convert_video_to_gif(input_path, output_path, start_time=None, end_time=None, fps=10, width=None):
    """Convert video to GIF using FFmpeg subprocess instead of loading whole video into memory"""
    import subprocess
    import shlex
    
    # Start building the FFmpeg command
    cmd = ['ffmpeg', '-i', input_path]
    
    # Add start time if specified
    if start_time is not None:
        cmd.extend(['-ss', str(start_time)])
    
    # Add end time if specified (as duration from start)
    if end_time is not None and start_time is not None:
        duration = end_time - start_time
        cmd.extend(['-t', str(duration)])
    elif end_time is not None:
        cmd.extend(['-to', str(end_time)])
    
    # Set framerate
    cmd.extend(['-r', str(fps)])
    
    # Set width if specified (maintain aspect ratio)
    if width is not None:
        cmd.extend(['-vf', f'scale={width}:-1:flags=lanczos'])
    
    # Add output options for GIF
    cmd.extend([
        '-f', 'gif',
        output_path
    ])
    
    # Execute the command
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"FFmpeg error: {result.stderr}")
    
    return True


@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # Clean old files first to free up space
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

            # Create unique filenames using timestamp
            timestamp = int(time.time())
            filename = f"{timestamp}_{secure_filename(file.filename)}"
            input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Save the uploaded file
            file.save(input_path)

            # Create output filename
            gif_filename = f"{os.path.splitext(filename)[0]}.gif"
            gif_path = os.path.join(app.config['OUTPUT_FOLDER'], gif_filename)
            static_gif_path = os.path.join('static', 'gifs', gif_filename)

            try:
                # Convert video to GIF using FFmpeg
                convert_video_to_gif(
                    input_path=input_path,
                    output_path=gif_path,
                    start_time=start_time,
                    end_time=end_time,
                    fps=fps,
                    width=width
                )

                # Instead of copying, just create a symlink to save disk space
                # (Remove previous link first if it exists)
                if os.path.exists(static_gif_path):
                    os.remove(static_gif_path)
                
                # Determine relative path for symlink
                rel_path = os.path.relpath(gif_path, os.path.dirname(static_gif_path))
                os.symlink(rel_path, static_gif_path)

                # Store minimal information in session
                session['gif_filename'] = gif_filename
                session['original_filename'] = os.path.basename(file.filename)
                session['gif_size'] = os.path.getsize(gif_path) / (1024 * 1024)  # Size in MB
                
                # Store file paths for later cleanup
                session['input_path'] = input_path
                session['gif_path'] = gif_path
                session['static_gif_path'] = static_gif_path

                # Delete the uploaded video immediately if not needed anymore
                # (uncomment if you don't need to keep originals)
                # delete_file_safely(input_path)
                
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


@app.route('/gifs/<filename>')
def download_file(filename):
    """Send the file for download and delete uploaded and generated files"""
    # Send the file first
    response = send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)

    # Schedule cleanup for after response is sent
    @response.call_on_close
    def cleanup_after_download():
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

            if static_gif_path and os.path.islink(static_gif_path):
                os.unlink(static_gif_path)
            elif static_gif_path:
                delete_file_safely(static_gif_path)

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


# Register periodic cleanup function to run on each request
@app.before_request
def cleanup_before_request():
    # Only run cleanup occasionally (1% of requests) to avoid overhead
    import random
    if random.random() < 0.01:
        clean_old_files(app.config['UPLOAD_FOLDER'], max_age_hours=1)
        clean_old_files(app.config['OUTPUT_FOLDER'], max_age_hours=1)
        clean_old_files(os.path.join('static', 'gifs'), max_age_hours=1)


if __name__ == '__main__':
    # Set a low number of worker threads to reduce memory usage
    app.run(debug=False, threaded=True, processes=1)
