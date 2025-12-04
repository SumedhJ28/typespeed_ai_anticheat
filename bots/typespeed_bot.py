#!/usr/bin/env python3
"""
Playwright-based TypeSpeedAI typing simulator.

Supports profiles:
 - superhuman  -> zero delay, perfect accuracy
 - bot_obvious -> fixed small delay
 - human_like  -> random delays, occasional mistakes/backspaces

Outputs JSON per-run logs to data/raw_logs/ and appends summary to data/raw_logs/runs_summary.csv

IMPORTANT: Update selectors in SELECTOR_* constants or populate bots/selectors.env
"""

import argparse
import csv
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# ---- Edit or fill bots/selectors.env with correct selectors ----
# If you prefer, set these in bots/selectors.env and the script will load them.
SELECTOR_TARGET_TEXT = "div.text-display-area"   # e.g. "div.type-text"
SELECTOR_HIDDEN_INPUT = "#typing-input"          # e.g. "input[type='text']" or "div[contenteditable='true']"
# Best-effort CSS selectors (preferred)
SELECTOR_RESULT_WPM = "//div[.//p[normalize-space(.)='Words per minute'] or .//div[normalize-space(.)='WPM']]//div[contains(@class,'text-2xl') and contains(@class,'font-bold')]"
SELECTOR_RESULT_ACCURACY = "#typing-practice-card .grid > div:nth-child(2) .text-2xl.font-bold.text-primary"

# ---------------------------------------------------------------

# ---------------------------------------------------------------

OUTPUT_DIR = Path("data/raw_logs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_selectors_from_env():
    env_path = Path("bots/selectors.env")
    selectors = {}
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    selectors[k.strip()] = v.strip()
    return selectors


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["superhuman", "bot_obvious", "human_like"], default="human_like",
                   help="Typing profile")
    p.add_argument("--site_mode", choices=["standard", "clean", "programmer"], default="standard",
                   help="Which test variant to choose on the site (if supported).")
    p.add_argument("--delay_min", type=int, default=40, help="Min delay ms for human_like")
    p.add_argument("--delay_max", type=int, default=220, help="Max delay ms for human_like")
    p.add_argument("--fixed_delay_ms", type=int, default=5, help="Delay ms for bot_obvious")
    p.add_argument("--iterations", type=int, default=1)
    p.add_argument("--headful", action="store_true", help="Run browser with UI")
    p.add_argument("--out_prefix", default="run", help="Prefix for JSON filenames")
    p.add_argument("--max_chars", type=int, default=5000, help="Safety max characters to type")
    return p.parse_args()


def choose_site_mode(page, mode: str):
    # Site-specific UI clicks to switch mode could go here.
    # This function is best-effort and safe to leave empty if site auto-selects.
    try:
        if mode == "standard":
            pass
        elif mode == "clean":
            pass
        elif mode == "programmer":
            pass
    except Exception:
        pass


def fallback_compute_wpm(keystroke_log, typed_chars_count):
    if not keystroke_log or len(keystroke_log) < 2:
        return 0.0
    start = keystroke_log[0]["timestamp"]
    end = keystroke_log[-1]["timestamp"]
    duration = max(0.001, end - start)
    minutes = duration / 60.0
    return (typed_chars_count / 5.0) / minutes if minutes > 0 else float("inf")


def type_text_profile(page, text, profile, args):
    """
    Types text using the selected profile. Returns keystroke log list.
    Each entry: {"key": str, "timestamp": float, "action": "keypress"|"backspace"}
    """
    log = []
    typed_count = 0

    # Attempt to focus: prefer hidden input selector if provided; otherwise click body
    try:
        if SELECTOR_HIDDEN_INPUT:
            page.wait_for_selector(SELECTOR_HIDDEN_INPUT, timeout=3000)
            page.click(SELECTOR_HIDDEN_INPUT)
        else:
            page.click("body")
    except Exception:
        try:
            page.click("body")
        except Exception:
            pass

    def do_type_char(ch):
        ts = time.time()
        try:
            # For multi-character like 'Enter' use press; else type single char
            if len(ch) > 1:
                page.keyboard.press(ch)
            else:
                page.keyboard.type(ch, delay=0)
        except Exception:
            # fallback: mutate input or dispatch keyboard event
            page.evaluate(
                """(c) => { window.dispatchEvent(new KeyboardEvent('keypress', {key: c})); }""",
                ch,
            )
        log.append({"key": ch, "timestamp": ts, "action": "keypress"})

    i = 0
    while i < len(text) and typed_count < args.max_chars:
        ch = text[i]
        if profile == "superhuman":
            do_type_char(ch)
            typed_count += 1
            i += 1
            # no delay
        elif profile == "bot_obvious":
            do_type_char(ch)
            typed_count += 1
            i += 1
            time.sleep(args.fixed_delay_ms / 1000.0)
        else:  # human_like
            # small chance to make a mistake and correct it
            if random.random() < 0.02 and i + 1 < len(text):
                wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
                do_type_char(wrong)
                time.sleep(random.uniform(args.delay_min, args.delay_max) / 1000.0)
                # backspace
                ts = time.time()
                try:
                    page.keyboard.press("Backspace")
                except Exception:
                    page.evaluate("() => { window.dispatchEvent(new KeyboardEvent('keydown', {key:'Backspace'})); }")
                log.append({"key": "Backspace", "timestamp": ts, "action": "backspace"})
                # then the correct char
                do_type_char(text[i])
                typed_count += 1
                i += 1
            else:
                do_type_char(ch)
                typed_count += 1
                i += 1
            time.sleep(random.uniform(args.delay_min, args.delay_max) / 1000.0)
    return log


def run_iteration(playwright, args, iteration_idx):
    browser = playwright.chromium.launch(headless=not args.headful)
    context = browser.new_context()
    page = context.new_page()

    meta = {
        "iteration": iteration_idx,
        "profile": args.mode,
        "site_mode": args.site_mode,
        "start_time": datetime.utcnow().isoformat() + "Z",
    }

    try:
        page.goto("https://typespeedai.com/", timeout=30000)
    except PwTimeout:
        print("Page load timed out.")
        browser.close()
        return None

    choose_site_mode(page, args.site_mode)

    # extract selectors from env if available
    env_sel = load_selectors_from_env()
    global SELECTOR_TARGET_TEXT, SELECTOR_HIDDEN_INPUT, SELECTOR_RESULT_WPM, SELECTOR_RESULT_ACCURACY
    SELECTOR_TARGET_TEXT = SELECTOR_TARGET_TEXT or env_sel.get("SELECTOR_TARGET_TEXT")
    SELECTOR_HIDDEN_INPUT = SELECTOR_HIDDEN_INPUT or env_sel.get("SELECTOR_HIDDEN_INPUT")
    SELECTOR_RESULT_WPM = SELECTOR_RESULT_WPM or env_sel.get("SELECTOR_RESULT_WPM")
    SELECTOR_RESULT_ACCURACY = SELECTOR_RESULT_ACCURACY or env_sel.get("SELECTOR_RESULT_ACCURACY")

    # Find target text
    try:
        if SELECTOR_TARGET_TEXT:
            target_elem = page.query_selector(SELECTOR_TARGET_TEXT)
            target_text = target_elem.inner_text() if target_elem else ""
        else:
            # fallback: attempt to find large text block
            target_text = page.evaluate(
                "(()=>{ const p = document.querySelector('main')||document.body; return p.innerText||'' })()"
            )
    except Exception as e:
        print("Error extracting text:", e)
        browser.close()
        return None

    if not target_text:
        print("Could not locate target text. Update SELECTOR_TARGET_TEXT in bots/selectors.env or the script.")
        browser.close()
        return None
    
    # Clean up text formatting for typing 
        
    if not target_text:
        print("Could not locate target text. Update SELECTOR_TARGET_TEXT in bots/selectors.env or the script.")
        browser.close()
        return None

    # ------- CLEAN TARGET TEXT (important to avoid accidental errors) -------
    # Normalize whitespace and collapse per-letter DOM splits while keeping real single-letter words.
    import re

    # convert NBSP and newlines into regular spaces
    target_text = (
        target_text.replace("\u00a0", " ")
                   .replace("\n", " ")
                   .replace("\r", " ")
    )

    # collapse multiple whitespace into a single space
    target_text = re.sub(r"\s+", " ", target_text).strip()

    # Collapse runs of single-letter alphabetic tokens (e.g. "t r u t h" -> "truth")
    # but keep isolated single-letter words (e.g. "I have") intact.
    tokens = target_text.split(" ")
    out_tokens = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        # check for single-letter alphabetic token
        if len(tok) == 1 and tok.isalpha():
            j = i
            run = []
            # gather a consecutive run of single-letter alphabetic tokens
            while j < n and len(tokens[j]) == 1 and tokens[j].isalpha():
                run.append(tokens[j])
                j += 1
            run_len = len(run)
            if run_len >= 2:
                # join the whole run into one word
                out_tokens.append("".join(run))
            else:
                # single-letter token (likely valid: "I" or "a") — keep as-is
                out_tokens.append(run[0])
            i = j
        else:
            out_tokens.append(tok)
            i += 1

    target_text = " ".join(out_tokens).strip()
    # ------------------------------------------------------------------------

    # Type the text
    print(f"[iter {iteration_idx}] Typing {len(target_text)} chars (profile={args.mode})...")

    keystroke_log = type_text_profile(page, target_text, args.mode, args)

    # wait a moment for result modal
    time.sleep(1.0)

    # Try to read page WPM & accuracy
    extracted_wpm = None
    extracted_accuracy = None
    try:
        if SELECTOR_RESULT_WPM:
            el = page.query_selector(SELECTOR_RESULT_WPM)
            if el:
                raw = el.inner_text().strip()
                import re
                m = re.search(r"(\d+\.?\d*)", raw)
                if m:
                    extracted_wpm = float(m.group(1))
    except Exception:
        pass
    try:
        if SELECTOR_RESULT_ACCURACY:
            el = page.query_selector(SELECTOR_RESULT_ACCURACY)
            if el:
                raw = el.inner_text().strip()
                import re
                m = re.search(r"(\d+\.?\d*)", raw)
                if m:
                    extracted_accuracy = float(m.group(1))
    except Exception:
        pass

    computed_wpm = fallback_compute_wpm(keystroke_log, typed_chars_count=len(target_text))
    if extracted_wpm is None:
        extracted_wpm = computed_wpm

    meta.update({
        "extracted_wpm": extracted_wpm,
        "extracted_accuracy": extracted_accuracy,
        "computed_wpm": computed_wpm,
        "keystrokes_count": len(keystroke_log),
        "end_time": datetime.utcnow().isoformat() + "Z",
    })

    # Save JSON
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    json_path = OUTPUT_DIR / f"{args.out_prefix}_{ts}_iter{iteration_idx}.json"
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump({"meta": meta, "keystroke_log": keystroke_log, "target_text_sample": target_text[:400]}, jf, indent=2)

    # Append summary CSV
    csv_path = OUTPUT_DIR / "runs_summary.csv"
    header = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        if header:
            writer.writerow(["iteration", "profile", "site_mode", "start_time", "end_time", "extracted_wpm",
                             "computed_wpm", "extracted_accuracy", "keystrokes_count", "json_file"])
        writer.writerow([meta["iteration"], meta["profile"], meta["site_mode"], meta["start_time"], meta["end_time"],
                         meta["extracted_wpm"], meta["computed_wpm"], meta.get("extracted_accuracy"),
                         meta["keystrokes_count"], json_path.name])

    browser.close()
    print(f"[iter {iteration_idx}] Saved {json_path}")
    return {"meta": meta, "keystroke_log": keystroke_log}

def main():
    args = parse_args()
    with sync_playwright() as pw:
        for i in range(1, args.iterations + 1):
            try:
                run_iteration(pw, args, i)
                time.sleep(0.5)
            except KeyboardInterrupt:
                print("Interrupted.")
                break
            except Exception as e:
                # Print the exception so we can debug unexpected errors
                print("Iteration error:", e)
                import traceback
                traceback.print_exc()
                continue
if __name__ == "__main__":
    main()


