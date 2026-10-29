import inspect
import os
import platform
import subprocess
import sys


def build():
    # определение ОС
    current_os = platform.system().lower()

    if "windows" in current_os:
        bin_name = "pyElite_Windows"
        is_windows = True
        print("Detected OS: Windows. Starting compilation...")
    elif "linux" in current_os:
        bin_name = "pyElite_Linux"
        is_windows = False
        print("Detected OS: Linux. Starting compilation...")
    else:
        # macOS или другие ОС
        bin_name = f"pyElite_{platform.system()}"
        is_windows = False
        print(f"Detected OS: {platform.system()}. Starting compilation...")

    # создание команды для pyinstaller
    command = [
        "pyinstaller",
        "--onefile",
        "--copy-metadata", "textual",
        f"--name={bin_name}",
        "elite_tui.py"
    ]

    # запуск построения сборки (все в одном файле) с выводом логов в консоль пользователя
    try:
        subprocess.run(command, check=True, stdout=None, stderr=None)
        print("Compilation completed successfully.")
    except subprocess.CalledProcessError:
        print("Error: pyinstaller compilation failed.", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: pyinstaller is not installed. Run 'pip install pyinstaller' first.", file=sys.stderr)
        sys.exit(1)

    # папка dist существует? создание README.md
    if os.path.exists("dist"):
        print("Creating README.md in dist/ folder...")
        readme_path = os.path.join("dist", "README.md")

        # 'шапка' файла README.md
        readme_text = """
        # pyElite Precompiled Binary

        This folder contains a precompiled executable file for pyElite. This binary includes the Python interpreter and all required dependencies, meaning you do not need to install Python 3.10+ on your system to play the game.
        """

        # условно добавляю блок для Linux/Windows
        if is_windows:
            readme_text += """
            ### Windows User Instructions

            1. Launch: Double-click the pyElite_Windows.exe file located in this folder. The game will automatically open in modern Windows Terminal.
            2. If Windows SmartScreen blocks the launch:
               * Windows will display a blue warning screen saying "Windows protected your PC".
               * Click the "More info" link under the text.
               * Click the "Run anyway" button that appears.

            #### Why do antiviruses flags this file?

            The game is packaged using PyInstaller, which bundles pure Python code into a single executable for your convenience so you do not need to install Python yourself. Due to the self-extraction mechanism into the temporary directory, some aggressive antivirus software may trigger a false positive on an unknown application without a digital signature. The project code is completely open-source (GPLv3). You can check it yourself in the repository and build the EXE from source using a single command:

            ```bash
            pip install pyinstaller && pyinstaller --onefile --copy-metadata textual --name=pyElite elite_tui.py
            ```
            """
        # условно добавляю блок для Linux/Windows
        else:
            readme_text += """
            ### Linux User Instructions

            1. Make it executable: Open your terminal, navigate to this folder, and grant execution permissions using the chmod command:
               ```bash
               chmod +x pyElite_Linux
               ```
            2. Launch: Run the binary directly from your terminal:
               ```bash
               ./pyElite_Linux
               ```
               * To force Russian or Spanish language interface, use the optional language flag:
               ```bash
               ./pyElite_Linux --lang ru
               ```

            #### Technical notes for Linux

            The binary is compiled against the glibc version present on the build system. It will run out of the box on most modern Linux distributions (such as recent Ubuntu, Fedora, Debian, and Arch). If you encounter any shared library or glibc version compatibility errors on older Linux systems, you can easily launch the game directly via Python or rebuild it from the source files using the instructions provided in the main README.md.

            Please note that this binary was specifically built on Debian 13. Due to this, users on older stable distributions (like Debian 12, Ubuntu 22.04 LTS, or older) will likely encounter a "GLIBC_X.XX not found" fatal error upon launch, as Debian 13 ships with a much newer version of the standard C library. If you experience this issue, please run the game using the native Python method instead of the precompiled binary.
            """

        # 'подвальный' блок для разработчика
        readme_text += """
        ---

        ## Building Executables from Source (For Developers)

        If you want to compile the game yourself into an independent executable, use PyInstaller.

        ### Prerequisites

        Ensure all base game dependencies are installed, then install PyInstaller:
        ```bash
        pip install pyinstaller
        ```

        ### Build on Linux
        ```bash
        pyinstaller --onefile --copy-metadata textual --name=pyElite_Linux elite_tui.py
        ```

        ### Build on Windows (Run inside Windows CMD/PowerShell)
        ```cmd
        pyinstaller --onefile --copy-metadata textual --name=pyElite_Windows elite_tui.py
        ```
        *Note:* Do not use the --noconsole or -w flag, as the full-screen interface of the Textual library requires a standard terminal window initialization.
        """

        # автоматическое удаление лишних отступов (TAB) из кода с сохранением верстки Markdown
        cleaned_content = inspect.cleandoc(readme_text)

        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(cleaned_content)

        print("README.md successfully created in dist/")
    else:
        print("Error: dist/ folder not found. Descriptions were not created.", file=sys.stderr)


if __name__ == "__main__":
    build()