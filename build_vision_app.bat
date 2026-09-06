@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD=python"
where py >nul 2>nul
if %errorlevel%==0 set "PYTHON_CMD=py -3"

echo [1/6] Checking Python...
%PYTHON_CMD% --version
if errorlevel 1 goto :python_error

echo [2/6] Checking runtime dependencies...
%PYTHON_CMD% -c "import PySide6, qtpy, cv2, numpy, mediapipe, dayu_widgets"
if errorlevel 1 goto :dependency_error

echo [3/6] Checking PyInstaller...
%PYTHON_CMD% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo PyInstaller is missing. Installing it into the current Python environment...
    %PYTHON_CMD% -m pip install pyinstaller
    if errorlevel 1 goto :pyinstaller_error
)

echo [4/6] Cleaning this application's previous build...
if exist "build\IronJumpVisionTools" rmdir /s /q "build\IronJumpVisionTools"
if exist "build\IronJumpVisionTools_build_info.json" del /q "build\IronJumpVisionTools_build_info.json"
if exist "dist\IronJumpVisionTools" rmdir /s /q "dist\IronJumpVisionTools"

echo [5/6] Capturing Git version and building onedir application...
%PYTHON_CMD% tools\write_build_info.py --output build\IronJumpVisionTools_build_info.json
if errorlevel 1 goto :build_error
%PYTHON_CMD% -m PyInstaller --noconfirm --clean IronJumpVisionTools.spec
if errorlevel 1 goto :build_error

echo [6/6] Build completed successfully.
echo Output: %CD%\dist\IronJumpVisionTools\IronJumpVisionTools.exe
if not exist "models\pose_landmarker_full.task" (
    echo NOTE: models\pose_landmarker_full.task was not bundled.
    echo       The application will ask the user to select it at runtime.
)
start "" "%CD%\dist\IronJumpVisionTools"
exit /b 0

:python_error
echo ERROR: Python 3 was not found. Install Python 3 and try again.
goto :failed

:dependency_error
echo ERROR: Project runtime dependencies are missing.
echo Install them first with: %PYTHON_CMD% -m pip install -r requirements.txt
echo Also ensure the project-local dayu_widgets directory is available on PYTHONPATH.
goto :failed

:pyinstaller_error
echo ERROR: PyInstaller could not be installed.
goto :failed

:build_error
echo ERROR: IronJumpVisionTools build failed. Review the output above.
goto :failed

:failed
pause
exit /b 1
