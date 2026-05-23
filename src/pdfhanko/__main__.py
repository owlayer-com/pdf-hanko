"""``python -m pdfhanko`` で実行された場合のエントリポイント。"""
import logging
import os

from .app import main

if __name__ == "__main__":
    exit_code = 0
    try:
        main().main_loop()
    except SystemExit as e:
        exit_code = int(e.code) if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        logging.getLogger("pdfhanko").critical("main_loop terminated with exception", exc_info=True)
        exit_code = 1
    finally:
        # Toga / rubicon-objc と Cocoa の autorelease pool 終了タイミング競合により、
        # Python finalize 後に C 側の main() が pool を drain する際、pool 内オブジェクトの
        # dealloc が ctypes 経由で死んだ PyInterpreterState を参照して SIGSEGV になる
        # (EXC_BAD_ACCESS at 0x28 in PyGILState_Ensure)。
        # HankoStore は変更時に都度永続化しているため、Python の通常 shutdown を経由せず
        # 即座に終了することで、終了時クラッシュを回避する。
        logging.shutdown()
        os._exit(exit_code)
