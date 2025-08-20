from app import app
import sys

if __name__ == '__main__':
    port = 5000
    if len(sys.argv) > 1 and sys.argv[1] == '--port':
        port = int(sys.argv[2])
    app.run(host='0.0.0.0', port=port, debug=True)
