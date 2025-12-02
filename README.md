🔧 Installation
1. Clone the repo
```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd typespeed_ai_anticheat
```

```2. Create virtual environment
python -m venv venv
```

```Activate (Windows):

.\venv\Scripts\activate
```
```3. Install dependencies
pip install -r requirements.txt
```
```4. Install Playwright browsers
python -m playwright install
```
🎯 Usage
```Run human-like simulation
python bots/typespeed_bot.py --mode human_like --iterations 5
```
```Bot-obvious simulation
python bots/typespeed_bot.py --mode bot_obvious --fixed_delay_ms 5 --iterations 3
```
```Superhuman bot simulation
python bots/typespeed_bot.py --mode superhuman --iterations 2
```
```Headful mode
python bots/typespeed_bot.py --headful

```
