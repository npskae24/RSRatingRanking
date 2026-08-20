"""
RS Rating Ranking — Web Dashboard
รันด้วย:  python app.py
เปิด:     http://localhost:5000
"""
import datetime
import glob
import json
import os
import queue
import subprocess
import sys
import threading

import pandas as pd
from flask import Flask, Response, jsonify, render_template, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_EXE = sys.executable

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))

# ── Global state ──────────────────────────────────────────────────────────────
_state = {
    'running': False,
    'status': 'idle',       # idle | running | done | error
    'started_at': None,
    'finished_at': None,
    'exit_code': None,
}
_log_queues: list = []
_state_lock = threading.Lock()


def _broadcast(msg: str):
    for q in list(_log_queues):
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


def _run_worker():
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    with _state_lock:
        _state.update(running=True, status='running',
                      started_at=datetime.datetime.now().isoformat(),
                      finished_at=None, exit_code=None)
    _broadcast(f'[{ts}] ▶ Script started.')

    try:
        proc = subprocess.Popen(
            [PYTHON_EXE, os.path.join(BASE_DIR, 'stock_ranking.py')],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            _broadcast(line.rstrip('\n'))
        proc.wait()
        code = proc.returncode
    except Exception as exc:
        _broadcast(f'[ERROR] {exc}')
        code = -1

    ts2 = datetime.datetime.now().strftime('%H:%M:%S')
    with _state_lock:
        _state['running'] = False
        _state['exit_code'] = code
        _state['finished_at'] = datetime.datetime.now().isoformat()
        _state['status'] = 'done' if code == 0 else 'error'

    if code == 0:
        _broadcast(f'[{ts2}] ✅ Script completed successfully.')
    else:
        _broadcast(f'[{ts2}] ❌ Script failed (exit code {code}).')
    _broadcast('__DONE__')


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/run', methods=['POST'])
def api_run():
    if _state['running']:
        return jsonify(ok=False, message='Script is already running.'), 409
    threading.Thread(target=_run_worker, daemon=True).start()
    return jsonify(ok=True)


@app.route('/api/status')
def api_status():
    return jsonify(**_state)


@app.route('/api/stream')
def api_stream():
    """Server-Sent Events — live log lines."""
    q: queue.Queue = queue.Queue(maxsize=5000)
    _log_queues.append(q)

    def generate():
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                except queue.Empty:
                    yield 'event: ping\ndata: \n\n'
                    continue
                if msg == '__DONE__':
                    yield 'event: done\ndata: \n\n'
                    return
                yield f'data: {json.dumps(msg)}\n\n'
        finally:
            try:
                _log_queues.remove(q)
            except ValueError:
                pass

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/results')
def api_results():
    """Return latest Excel output as JSON (top 200 by RS Rating)."""
    files = sorted(
        glob.glob(os.path.join(BASE_DIR, '????????.xlsx')),
        key=os.path.getmtime, reverse=True,
    )
    if not files:
        return jsonify(ok=False, message='No result files found yet. Run the script first.')
    path = files[0]
    try:
        xf = pd.ExcelFile(path)
        sheet = xf.sheet_names[-1]
        df = pd.read_excel(path, sheet_name=sheet, index_col=0)

        # Select columns to display
        rs_col = next((c for c in df.columns if 'RS Rating' in str(c)), None)
        display = [rs_col] if rs_col else []
        for c in ['RS Score', 'Close Price']:
            if c in df.columns:
                display.append(c)
        for c in ['marketCap', 'ROE', 'profitMargins', 'revenueGrowth',
                  'earningGrowth', '52wHighToClosePrice']:
            if c in df.columns:
                display.append(c)

        df_out = df[display].head(200) if display else df.head(200)
        df_out = df_out.copy()
        df_out.index = [str(i).replace('.BK', '') for i in df_out.index]
        df_out = df_out.round(4)
        records = df_out.reset_index().rename(columns={'index': 'Symbol'}).to_dict(orient='records')

        return jsonify(
            ok=True,
            file=os.path.basename(path),
            sheet=sheet,
            columns=['Symbol'] + list(df_out.columns),
            data=records,
        )
    except Exception as exc:
        return jsonify(ok=False, message=str(exc))


@app.route('/api/watchlist')
def api_watchlist():
    files = sorted(
        glob.glob(os.path.join(BASE_DIR, 'watchlist_*.txt')),
        key=os.path.getmtime, reverse=True,
    )
    if not files:
        return jsonify(ok=False, message='No watchlist found yet.')
    with open(files[0]) as f:
        content = f.read().strip()
    stocks = [s for s in content.split('\n') if s]
    return jsonify(ok=True, file=os.path.basename(files[0]),
                   stocks=stocks, raw=content, count=len(stocks))


@app.route('/api/files')
def api_files():
    files = sorted(
        glob.glob(os.path.join(BASE_DIR, '????????.xlsx')),
        key=os.path.getmtime, reverse=True,
    )[:30]
    return jsonify(ok=True, files=[os.path.basename(f) for f in files])


@app.route('/download/<path:filename>')
def download(filename):
    safe = os.path.basename(filename)
    if not safe.endswith('.xlsx'):
        return 'Forbidden', 403
    return send_from_directory(BASE_DIR, safe, as_attachment=True)


if __name__ == '__main__':
    print('=' * 55)
    print('  RS Rating Ranking — Web Dashboard')
    print('  http://localhost:5000')
    print('=' * 55)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
