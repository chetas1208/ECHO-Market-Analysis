# Day 6 Forecast Evaluation

Status: **complete**

```json
{
  "ablations": {
    "without_absorption": {
      "10D": {
        "directional_accuracy": 0.3333333333333333,
        "mae": 0.021062510784158918,
        "rmse": 0.021833362550016548,
        "spearman": -0.8333333333333334
      },
      "1D": {
        "directional_accuracy": 0.2222222222222222,
        "mae": 0.00996181961472125,
        "rmse": 0.012567038627341733,
        "spearman": -0.9
      },
      "20D": {
        "directional_accuracy": 0.6666666666666666,
        "mae": 0.02687947939555176,
        "rmse": 0.03141694552192012,
        "spearman": -0.8666666666666667
      },
      "2D": {
        "directional_accuracy": 0.1111111111111111,
        "mae": 0.017935579072196218,
        "rmse": 0.020203023598076634,
        "spearman": -0.95
      },
      "5D": {
        "directional_accuracy": 0.4444444444444444,
        "mae": 0.007805451906023454,
        "rmse": 0.00810156525353557,
        "spearman": -0.55
      }
    },
    "without_cause": {
      "10D": {
        "directional_accuracy": 1.0,
        "mae": 0.009107125843907939,
        "rmse": 0.012062154678479107,
        "spearman": -0.6666666666666666
      },
      "1D": {
        "directional_accuracy": 0.3333333333333333,
        "mae": 0.01112919998502279,
        "rmse": 0.01282318471676428,
        "spearman": -1.0
      },
      "20D": {
        "directional_accuracy": 0.3333333333333333,
        "mae": 0.044389115259927586,
        "rmse": 0.04758839991638979,
        "spearman": -0.8166666666666667
      },
      "2D": {
        "directional_accuracy": 0.1111111111111111,
        "mae": 0.016576636595831636,
        "rmse": 0.020876454409566002,
        "spearman": -1.0
      },
      "5D": {
        "directional_accuracy": 0.2222222222222222,
        "mae": 0.019495796104964866,
        "rmse": 0.024722842074439234,
        "spearman": -0.9333333333333333
      }
    },
    "without_event": {
      "10D": {
        "directional_accuracy": 1.0,
        "mae": 0.01203994825898562,
        "rmse": 0.016950460905464385,
        "spearman": -0.43333333333333335
      },
      "1D": {
        "directional_accuracy": 0.0,
        "mae": 0.035240887735777666,
        "rmse": 0.040025573202568755,
        "spearman": -1.0
      },
      "20D": {
        "directional_accuracy": 1.0,
        "mae": 0.019819848793164414,
        "rmse": 0.02767596541141666,
        "spearman": -0.5
      },
      "2D": {
        "directional_accuracy": 0.1111111111111111,
        "mae": 0.00691776643906246,
        "rmse": 0.007522552992701007,
        "spearman": -0.95
      },
      "5D": {
        "directional_accuracy": 0.2222222222222222,
        "mae": 0.019255057449116528,
        "rmse": 0.022480580707221295,
        "spearman": -0.95
      }
    },
    "without_graph": {
      "10D": {
        "directional_accuracy": 0.5555555555555556,
        "mae": 0.019619430615116507,
        "rmse": 0.022234948609138376,
        "spearman": -0.8
      },
      "1D": {
        "directional_accuracy": 0.1111111111111111,
        "mae": 0.004118527482691603,
        "rmse": 0.005065482488473533,
        "spearman": -1.0
      },
      "20D": {
        "directional_accuracy": 0.7777777777777778,
        "mae": 0.017873682043384003,
        "rmse": 0.021325447594408676,
        "spearman": -0.8666666666666667
      },
      "2D": {
        "directional_accuracy": 0.7777777777777778,
        "mae": 0.014415514728910351,
        "rmse": 0.016481279163963504,
        "spearman": 0.4
      },
      "5D": {
        "directional_accuracy": 0.2222222222222222,
        "mae": 0.017055175997601778,
        "rmse": 0.023186466891404245,
        "spearman": -0.95
      }
    }
  },
  "baselines": {
    "10D": {
      "chronos_only": {
        "status": "BASELINE_UNAVAILABLE"
      },
      "exposure_only": {
        "directional_accuracy": 0.5555555555555556,
        "mae": 0.009079473319220205,
        "rmse": 0.009215491567915396,
        "spearman": 1.0
      },
      "historical_mean": {
        "directional_accuracy": 0.0,
        "mae": 0.01396380072349136,
        "rmse": 0.01470233577646145,
        "spearman": null
      },
      "selected_model": {
        "directional_accuracy": 0.7777777777777778,
        "mae": 0.018213590188917782,
        "rmse": 0.02103346665236361,
        "spearman": -0.7833333333333333
      },
      "zero": {
        "directional_accuracy": 0.0,
        "mae": 0.009379473319220205,
        "rmse": 0.010447270762472087,
        "spearman": null
      }
    },
    "1D": {
      "chronos_only": {
        "status": "BASELINE_UNAVAILABLE"
      },
      "exposure_only": {
        "directional_accuracy": 0.8888888888888888,
        "mae": 0.0019199999999999996,
        "rmse": 0.0021800458710770285,
        "spearman": 1.0
      },
      "historical_mean": {
        "directional_accuracy": 0.3333333333333333,
        "mae": 0.0016381481481481481,
        "rmse": 0.0020421094757899516,
        "spearman": null
      },
      "selected_model": {
        "directional_accuracy": 0.0,
        "mae": 0.03408859133537264,
        "rmse": 0.042571246102244276,
        "spearman": -0.9333333333333333
      },
      "zero": {
        "directional_accuracy": 0.0,
        "mae": 0.0014600000000000001,
        "rmse": 0.0017235428628264513,
        "spearman": null
      }
    },
    "20D": {
      "chronos_only": {
        "status": "BASELINE_UNAVAILABLE"
      },
      "exposure_only": {
        "directional_accuracy": 0.5555555555555556,
        "mae": 0.018236656314599947,
        "rmse": 0.018624654123090768,
        "spearman": 1.0
      },
      "historical_mean": {
        "directional_accuracy": 0.0,
        "mae": 0.027655913273399935,
        "rmse": 0.02847490411299428,
        "spearman": null
      },
      "selected_model": {
        "directional_accuracy": 0.6666666666666666,
        "mae": 0.03505834799370286,
        "rmse": 0.03869614206692466,
        "spearman": -0.85
      },
      "zero": {
        "directional_accuracy": 0.0,
        "mae": 0.01853665631459995,
        "rmse": 0.019737736764482344,
        "spearman": null
      }
    },
    "2D": {
      "chronos_only": {
        "status": "BASELINE_UNAVAILABLE"
      },
      "exposure_only": {
        "directional_accuracy": 0.7777777777777778,
        "mae": 0.0017760471392495776,
        "rmse": 0.002241739433486469,
        "spearman": 1.0
      },
      "historical_mean": {
        "directional_accuracy": 0.2222222222222222,
        "mae": 0.002907417989148053,
        "rmse": 0.0035161572226815483,
        "spearman": null
      },
      "selected_model": {
        "directional_accuracy": 0.1111111111111111,
        "mae": 0.011872943533896726,
        "rmse": 0.013281192642688445,
        "spearman": -0.9333333333333333
      },
      "zero": {
        "directional_accuracy": 0.0,
        "mae": 0.0022546060590600664,
        "rmse": 0.00279106117989898,
        "spearman": null
      }
    },
    "5D": {
      "chronos_only": {
        "status": "BASELINE_UNAVAILABLE"
      },
      "exposure_only": {
        "directional_accuracy": 0.6666666666666666,
        "mae": 0.004468328157299975,
        "rmse": 0.004521175276781663,
        "spearman": 1.0
      },
      "historical_mean": {
        "directional_accuracy": 0.1111111111111111,
        "mae": 0.007077956636699969,
        "rmse": 0.007758659569043168,
        "spearman": null
      },
      "selected_model": {
        "directional_accuracy": 0.8888888888888888,
        "mae": 0.004871341267257316,
        "rmse": 0.006489952432476985,
        "spearman": -0.7166666666666667
      },
      "zero": {
        "directional_accuracy": 0.0,
        "mae": 0.004769793535566562,
        "rmse": 0.005730295068580653,
        "spearman": null
      }
    }
  },
  "chronos": {
    "model": "amazon/chronos-2",
    "status": "BASELINE_UNAVAILABLE"
  },
  "dataset": {
    "dataset_hash": "1ffa092972707da5f0d64129187e789f48b28a944d3c3497ee3375f3fd496f7e",
    "date_end": "2025-01-16T14:30:00+00:00",
    "date_start": "2025-01-02T14:30:00+00:00",
    "events": 15,
    "rows": 45,
    "symbols": [
      "AMD",
      "NVDA",
      "XOM"
    ]
  },
  "leakage": {
    "calibration_fit": "validation_only",
    "chronological": true,
    "event_group_aware": true,
    "scaler_fit": "train_only"
  },
  "metrics": {
    "10D": {
      "coverage_80": 1.0,
      "directional_accuracy": 0.7777777777777778,
      "interval_width": 0.14243538142686687,
      "mae": 0.018213590188917782,
      "pinball_q10": 0.006807631569226513,
      "pinball_q50": 0.009106795094458891,
      "pinball_q90": 0.0074359065734601725,
      "rmse": 0.02103346665236361,
      "test_rows": 9
    },
    "1D": {
      "coverage_80": 1.0,
      "directional_accuracy": 0.0,
      "interval_width": 0.19459561688950217,
      "mae": 0.03408859133537264,
      "pinball_q10": 0.011202647054805484,
      "pinball_q50": 0.01704429566768632,
      "pinball_q90": 0.00825691463414473,
      "rmse": 0.042571246102244276,
      "test_rows": 9
    },
    "20D": {
      "coverage_80": 1.0,
      "directional_accuracy": 0.6666666666666666,
      "interval_width": 0.17268233351776105,
      "mae": 0.03505834799370286,
      "pinball_q10": 0.00908649506858402,
      "pinball_q50": 0.01752917399685143,
      "pinball_q90": 0.008181738283192082,
      "rmse": 0.03869614206692466,
      "test_rows": 9
    },
    "2D": {
      "coverage_80": 1.0,
      "directional_accuracy": 0.1111111111111111,
      "interval_width": 0.08536493848059913,
      "mae": 0.011872943533896726,
      "pinball_q10": 0.005289160151564465,
      "pinball_q50": 0.005936471766948363,
      "pinball_q90": 0.0032473336964954475,
      "rmse": 0.013281192642688445,
      "test_rows": 9
    },
    "5D": {
      "coverage_80": 1.0,
      "directional_accuracy": 0.8888888888888888,
      "interval_width": 0.08684214667666083,
      "mae": 0.004871341267257316,
      "pinball_q10": 0.005258075841508974,
      "pinball_q50": 0.002435670633628658,
      "pinball_q90": 0.0034261388261571093,
      "rmse": 0.006489952432476985,
      "test_rows": 9
    }
  },
  "model": {
    "artifact_hash": "e1065d87087263b43e7638fe71a86dbf97da00ea99e45e79927a258ba409efcf",
    "backend": "linear_pinball_fallback",
    "version": "echo-forecast-v1-1ffa09297270"
  },
  "split": {
    "dataset_hash": "1ffa092972707da5f0d64129187e789f48b28a944d3c3497ee3375f3fd496f7e",
    "event_groups": 15,
    "test_end": "2025-01-16 14:30:00+00:00",
    "test_groups": [
      "fixture_event_12",
      "fixture_event_13",
      "fixture_event_14"
    ],
    "test_start": "2025-01-14 14:30:00+00:00",
    "train_end": "2025-01-10 14:30:00+00:00",
    "train_groups": [
      "fixture_event_00",
      "fixture_event_01",
      "fixture_event_02",
      "fixture_event_03",
      "fixture_event_04",
      "fixture_event_05",
      "fixture_event_06",
      "fixture_event_07",
      "fixture_event_08"
    ],
    "train_start": "2025-01-02 14:30:00+00:00",
    "validation_end": "2025-01-13 14:30:00+00:00",
    "validation_groups": [
      "fixture_event_09",
      "fixture_event_10",
      "fixture_event_11"
    ],
    "validation_start": "2025-01-11 14:30:00+00:00"
  },
  "status": "complete",
  "target_distributions": {
    "10D": {
      "count": 45,
      "max": 0.016571573107523288,
      "mean": 0.0,
      "min": -0.016571573107523288
    },
    "1D": {
      "count": 45,
      "max": 0.00297,
      "mean": 0.0,
      "min": -0.00297
    },
    "20D": {
      "count": 45,
      "max": 0.02958650103359919,
      "mean": 0.0,
      "min": -0.02958650103359919
    },
    "2D": {
      "count": 45,
      "max": 0.004815290039756342,
      "mean": 0.0,
      "min": -0.004815290039756342
    },
    "5D": {
      "count": 45,
      "max": 0.009543250516799596,
      "mean": 0.0,
      "min": -0.009543250516799596
    }
  }
}
```
