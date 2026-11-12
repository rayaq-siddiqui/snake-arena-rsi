# RSI run: snake:trapper

- proposer: `gaussian_hill_climb`; rule: `PairedBootstrapRule` (min gain 2%, 10,000 bootstrap resamples)
- run seed 1240441715; framework v1, code 7938b639809c2627
- generations: 4; accepted: 0; stopped by: no accept in 4 generations
- episodes used: 480

## Final check (champion vs generation-0 baseline on the final seeds)

Nothing was accepted; the champion is still the baseline.

## Champion parameters

| parameter | baseline | champion |
|---|---|---|
| w_immediate_death | -1000 | -1000 |
| space_cap | 60 | 60 |
| search_radius | 12 | 12 |
| trap_margin | 2 | 2 |
| keep_distance | 3 | 3 |
| keep_repel | 1 | 1 |
| pull_radius | 15 | 15 |
| random_tiebreak | 1 | 1 |
| w_head_on_risk | -40 | -40 |
| w_territory | 20 | 20 |
| w_space | 6 | 6 |
| w_space_vs_length | 20 | 20 |
| w_enemy_space_after | -15 | -15 |
| w_enemy_escape_moves | -10 | -10 |
| w_nearest_enemy_head | -20 | -20 |
| w_straightness | 0.01 | 0.01 |
| w_cut_off | 4 | 4 |

## Decisions

| gen | candidate | stage | dev diff | holdout diff | holdout CI | accepted | why |
|---|---|---|---|---|---|---|---|
| 1 | 7c8846aa | dev | -0.025 | - | - | no | dev mean difference -0.025 is not above 0 |
| 2 | 551fa9fc | holdout | +0.1 | -0.0125 | [-0.163, +0.125] | no | holdout gain -6.3%, 95% CI [-0.1625, +0.125]: below the 2% minimum gain |
| 3 | abd1a3ca | holdout | +0.1 | +0 | [-0.1, +0.1] | no | holdout gain +0.0%, 95% CI [-0.1, +0.1]: below the 2% minimum gain |
| 4 | 6759caef | dev | +0 | - | - | no | dev mean difference +0 is not above 0 |
