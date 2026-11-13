⚡ PC Analyzer

PC Analyzer is a free Windows desktop app, inspired by CPU-Z, that identifies your PC’s hardware, rates your build and tells you how to improve it. The interface is in Italian.

✨ What it can do
- 🔍 Hardware detection: CPU, motherboard and BIOS, RAM (each module), graphics cards, SSDs/HDDs and operating system. No admin rights needed.
- ⭐ Build rating: a score from 1 to 5 (with half points) for Gaming, Office and Productivity, plus an overall score. Ratings take into account how old the components are compared with today’s standards.
- ⚖️ Balance check: spots bottlenecks (CPU vs GPU, too little or single-channel RAM, Windows on an HDD, XMP/EXPO disabled…) and gives the build a balance score from 0 to 100.
- 🛒 Upgrade suggestions: compatible parts with estimated prices and a preview of how your scores would change. Prices can be refreshed with an AI web search or from an online price list.
- 🌐 Internet speed test: download, upload, ping and jitter (Cloudflare or Ookla).
- 🧩 Drivers: direct links to the official driver and BIOS pages for your motherboard, chipset and graphics card.
- 🤖 AI assistant (optional): an in-depth analysis and free-form questions powered by Claude. Requires your own Anthropic API key.
- 📄 Report export (TXT/JSON) and 🔄 automatic updates from GitHub.

🚀 How to install
Install Python 3.10 or newer from python.org. In the installer, check “Add python.exe to PATH”.
Download this repository (Code → Download ZIP) and extract it.
Double-click avvia.bat: it installs the required libraries and starts the app.
(Optional) Double-click build_exe.bat to create a standalone PCAnalyzer.exe in dist\PCAnalyzer. That version runs without Python.
