"""
TensorTrade Proof of Concept — Go/No-Go Evaluation
Train PPO agent on SPY daily OHLCV 2006-2020, test on 2021-2025.
Compare vs SPY buy-and-hold. If agent doesn't beat SPY in test period → park it.

NOTE: TensorTrade (github.com/tensortrade-org/tensortrade) is NOT pip-installable
as of 2026 — the project has been largely unmaintained since 2022.
This module implements a minimal self-contained RL environment using gymnasium + stable-baselines3.
Same concept, avoids the dead library dependency.

Install:
    pip install gymnasium stable-baselines3 yfinance pandas numpy
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

TRAIN_START = "2006-01-01"
TRAIN_END = "2020-12-31"
TEST_START = "2021-01-01"
TEST_END = "2025-12-31"
RESULTS_DIR = Path(__file__).parent / "results"


def _check_deps() -> bool:
    try:
        import gymnasium  # noqa: F401
        from stable_baselines3 import PPO  # noqa: F401
        return True
    except ImportError:
        return False


def _load_spy(start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    spy = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False)
    spy = spy.rename(columns=str.lower)
    spy["return"] = spy["close"].pct_change()
    spy["log_return"] = np.log(spy["close"] / spy["close"].shift(1))
    # 5-day momentum, 20-day vol, RSI-14
    spy["mom_5d"] = spy["close"] / spy["close"].shift(5) - 1
    spy["mom_20d"] = spy["close"] / spy["close"].shift(20) - 1
    delta = spy["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    spy["rsi_14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    spy["vol_20d"] = spy["return"].rolling(20).std()
    spy = spy.dropna()
    return spy


class SPYTradingEnv:
    """
    Minimal Gymnasium-compatible trading environment for SPY.
    State:  [mom_5d, mom_20d, rsi_14/100, vol_20d, position]
    Action: 0 = flat, 1 = long, 2 = short
    Reward: daily portfolio return (position * next_day_return)
    """

    OBSERVATION_SIZE = 5

    def __init__(self, df: pd.DataFrame):
        self.df = df.reset_index(drop=True)
        self.n = len(df)
        self.pos = 0
        self.t = 0

    def reset(self) -> np.ndarray:
        self.t = 0
        self.pos = 0
        return self._obs()

    def step(self, action: int) -> tuple[np.ndarray, float, bool, dict]:
        # action: 0=flat, 1=long, 2=short
        self.pos = {0: 0, 1: 1, 2: -1}[action]
        self.t += 1
        done = self.t >= self.n - 1
        if done:
            return self._obs(), 0.0, True, {}
        next_ret = float(self.df.loc[self.t, "return"])
        reward = self.pos * next_ret
        return self._obs(), reward, done, {}

    def _obs(self) -> np.ndarray:
        row = self.df.iloc[min(self.t, self.n - 1)]
        return np.array([
            row["mom_5d"],
            row["mom_20d"],
            row["rsi_14"] / 100.0,
            row["vol_20d"] * 10,
            float(self.pos),
        ], dtype=np.float32)


def _simulate_agent(env: SPYTradingEnv, model) -> tuple[pd.Series, float]:
    """Run trained model on env, return daily returns and Sharpe."""
    obs = env.reset()
    returns = []
    done = False
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, _ = env.step(int(action))
        returns.append(reward)
    r = pd.Series(returns)
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
    return r, sharpe


def _cagr(returns: pd.Series) -> float:
    n_years = len(returns) / 252
    return float((1 + returns).prod() ** (1 / n_years) - 1) if n_years > 0 else 0.0


def run_poc() -> dict:
    """
    Train PPO on SPY 2006-2020, test on 2021-2025.
    Returns dict with go/no-go recommendation and metrics.
    """
    if not _check_deps():
        return {
            "status": "SKIPPED",
            "reason": "gymnasium or stable-baselines3 not installed. Run: pip install gymnasium stable-baselines3",
        }

    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.env_util import make_vec_env
    except ImportError as e:
        return {"status": "SKIPPED", "reason": str(e)}

    log.info("TensorTrade PoC: loading SPY data...")
    train_df = _load_spy(TRAIN_START, TRAIN_END)
    test_df = _load_spy(TEST_START, TEST_END)

    spy_train_cagr = _cagr(train_df["return"])
    spy_test_cagr = _cagr(test_df["return"])

    log.info(f"SPY train CAGR: {spy_train_cagr:.2%}  |  SPY test CAGR: {spy_test_cagr:.2%}")

    # Wrap environment for stable-baselines3
    # sb3 requires gymnasium.Env interface — we wrap our simple env
    try:
        import gymnasium as gym
        from gymnasium import spaces

        class SB3Env(gym.Env):
            metadata = {}

            def __init__(self, df):
                super().__init__()
                self._inner = SPYTradingEnv(df)
                self.observation_space = spaces.Box(
                    low=-10, high=10, shape=(SPYTradingEnv.OBSERVATION_SIZE,), dtype=np.float32
                )
                self.action_space = spaces.Discrete(3)

            def reset(self, *, seed=None, options=None):
                obs = self._inner.reset()
                return obs, {}

            def step(self, action):
                obs, reward, done, info = self._inner.step(action)
                return obs, reward, done, False, info

        log.info("Training PPO agent (2006-2020)...")
        train_env = SB3Env(train_df)
        model = PPO("MlpPolicy", train_env, verbose=0, n_steps=512, batch_size=64, n_epochs=5)
        model.learn(total_timesteps=len(train_df) * 10)

        log.info("Evaluating on test period (2021-2025)...")
        test_env = SPYTradingEnv(test_df)
        test_returns, test_sharpe = _simulate_agent(test_env, model)
        agent_test_cagr = _cagr(test_returns)

        beats = agent_test_cagr > spy_test_cagr
        verdict = "GO" if beats else "NO-GO"

        results = {
            "status": "COMPLETE",
            "verdict": verdict,
            "spy_train_cagr": round(spy_train_cagr, 4),
            "spy_test_cagr": round(spy_test_cagr, 4),
            "agent_test_cagr": round(agent_test_cagr, 4),
            "agent_test_sharpe": round(test_sharpe, 3),
            "beats_spy_in_test": beats,
            "recommendation": (
                "Proceed with TensorTrade position-sizing wrapper for EPM ensemble."
                if beats else
                "Park TensorTrade — PPO agent does not beat SPY buy-and-hold in out-of-sample "
                "2021-2025 test. Revisit if momentum/vol features succeed and warrant a sizing layer."
            ),
        }

        output_path = RESULTS_DIR / "tensortrade_poc.json"
        import json
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)

        log.info(f"\n=== TensorTrade PoC Result: {verdict} ===")
        log.info(f"  SPY test CAGR:    {spy_test_cagr:.2%}")
        log.info(f"  Agent test CAGR:  {agent_test_cagr:.2%}")
        log.info(f"  Agent Sharpe:     {test_sharpe:.2f}")
        log.info(f"  {results['recommendation']}")
        log.info(f"  Saved → {output_path}")

        return results

    except Exception as exc:
        log.error(f"TensorTrade PoC failed: {exc}", exc_info=True)
        return {"status": "ERROR", "reason": str(exc)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run_poc()
    if result["status"] == "SKIPPED":
        print(f"\nSkipped: {result['reason']}")
    elif result["status"] == "COMPLETE":
        print(f"\nVerdict: {result['verdict']}")
        print(result["recommendation"])
