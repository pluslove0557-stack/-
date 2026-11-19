"""실행 진입점.

기본은 이 PC에서만(127.0.0.1) 열리고 디버그는 꺼져 있다.
    python run.py                  실행 (브라우저 자동 열림)
    python run.py --set-password   잠금 비밀번호 설정/변경
    python run.py --no-browser     브라우저를 열지 않음
환경변수: HOST(기본 127.0.0.1), PORT(기본 5000), APP_DEBUG=1
"""

import os
import sys
import threading
import webbrowser

from app import create_app

app = create_app()


def _set_password():
    import getpass

    from app.auth import save_password

    pw = getpass.getpass("새 비밀번호 (입력 내용은 화면에 보이지 않습니다): ")
    if len(pw) < 4:
        print("4자 이상으로 정해 주세요. 변경하지 않았습니다.")
        return 1
    if getpass.getpass("한 번 더 입력: ") != pw:
        print("두 입력이 다릅니다. 변경하지 않았습니다.")
        return 1
    save_password(pw)
    print("비밀번호를 저장했습니다. 다음 실행부터 로그인이 필요합니다.")
    return 0


if __name__ == "__main__":
    if "--set-password" in sys.argv:
        sys.exit(_set_password())
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("APP_DEBUG") == "1"
    if "--no-browser" not in sys.argv and not debug:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    app.run(host=host, port=port, debug=debug)
