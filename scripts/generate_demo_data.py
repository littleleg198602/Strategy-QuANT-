from pathlib import Path

from strategy_quant.demo import make_demo_bars


def main() -> None:
    target = Path("data/EURUSD_H1_demo.csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    make_demo_bars().reset_index().to_csv(target, index=False)
    print(target)


if __name__ == "__main__":
    main()

