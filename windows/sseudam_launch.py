# -*- coding: utf-8 -*-
"""마이크로소프트 스토어(MSIX)판 시작점: pythonw.exe -m sseudam_launch
스토어 앱은 작업 폴더가 System32라서 파일 경로 대신 모듈로 실행하고, 스토어판 표시(SSEUDAM_MSIX)를 붙여 launcher.pyw 를 돌린다."""
import os
import runpy

os.environ["SSEUDAM_MSIX"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
runpy.run_path(os.path.join(HERE, "launcher.pyw"), run_name="__main__")
