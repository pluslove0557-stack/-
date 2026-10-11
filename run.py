import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # 기본은 이 컴퓨터에서만 접속 가능(127.0.0.1). 같은 와이파이의 다른 기기에서
    # 쓰려면 STUDIO_HOST=0.0.0.0 으로 실행하세요(비밀번호 잠금은 그대로 적용됨).
    host = os.environ.get("STUDIO_HOST", "127.0.0.1")
    port = int(os.environ.get("STUDIO_PORT", "5000"))
    # 디버그 모드는 원격 코드 실행 위험이 있어 로컬 바인딩일 때만 허용
    debug = os.environ.get("STUDIO_DEBUG") == "1" and host == "127.0.0.1"
    app.run(host=host, port=port, debug=debug)
