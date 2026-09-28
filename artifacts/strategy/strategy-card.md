# ECHO Residual Propagation

Universe: liquid equities, with benchmark ETFs for comparison and optional hedge variants.

Signal: event confidence × signed ShockGraph exposure × forecast direction and probability × underabsorption × moderate market confirmation.

Entry: next available bar after the decision cutoff; long and short are symmetric.

Exit: 1D/2D/5D horizon or 1.5-risk-unit stop, including costs.

Risk: 0.75% per trade, 20% single-name cap, 5 positions, 2 per sector, 5% drawdown kill switch.

Historical validation: not promoted from the checked-in synthetic smoke fixture; empirical performance requires a timestamped event archive and compatible market bars.

Known weakness: the current repository has no defensible multi-year event archive, so no Sharpe or final-holdout claim is made.
