import concurrent.futures
from collections import namedtuple
from dataclasses import dataclass, field
from math import comb
from mmr_systems.common.common import (ContestRatingParams, RatingSystem,
                                       TeamRatingAggregation, TeamRatingSystem)
from mmr_systems.common.player import Player
from mmr_systems.common.term import Rating

KFactor = namedtuple('KFactor', ['k', 'games', 'rating'])
TeamRating = namedtuple('TeamRating', ['team', 'rank', 'rating'])


@dataclass
class Elo(RatingSystem, TeamRatingSystem):
    beta: float = 400
    k_factors: list[KFactor] = field(default_factory=list)

    def round_update(self,
                     params: ContestRatingParams,
                     standings: list[tuple[Player, int, int]]) -> None:
        raise NotImplementedError()

    @staticmethod
    def _standard_performance_rating(opp_ratings: list[float], wins: int, loses: int, s: float):
        return (sum(opp_rating for opp_rating in opp_ratings) + s * (wins - loses)) / len(opp_ratings)

    @staticmethod
    def _win_probability(rating_i: float, rating_j: float, s: float) -> float:
        return 1. / (1 + 10 ** ((rating_j - rating_i) / s))

    @staticmethod
    def _r(N: int, rank_i: int):
        return (N - rank_i) / comb(N, 2)

    def k_factor(self, games: int, rating: float, default: int = 40) -> int:
        for k_factor in self.k_factors:
            if k_factor.games and k_factor.rating and k_factor.games > games and k_factor.rating > rating:
                return k_factor.k
            elif k_factor.games and k_factor.games > games:
                return k_factor.k
            elif k_factor.rating and k_factor.rating > rating:
                return k_factor.k
        return default

    def team_round_update(self,
                          params: ContestRatingParams,
                          standings: list[tuple[Player, int, int]],
                          agg: TeamRatingAggregation) -> None:

        s = self.beta / (params.weight ** 0.5)
        self.init_players_event(standings)
        team_standings = self.convert_to_teams(standings)
        team_ratings = list(TeamRating(team, team_info['rank'], agg(team_info['players'])) for team, team_info in team_standings.items())
        N = len(team_ratings)
        prob_denom = comb(N, 2)
        k = 40 * params.weight

        def _update_player_rating(relative_rank: int, team_i: TeamRating):
            team_i_mu = team_i.rating.mu
            r_i = (N - relative_rank) / prob_denom
            total_probabilty = 0.
            for team_q in team_ratings:
                if team_i is team_q:
                    continue
                total_probabilty += Elo._win_probability(team_i.rating.mu, team_q.rating.mu, s)
            total_probabilty /= prob_denom
            team_new_mu = team_i.rating.mu + k * (r_i - total_probabilty)
            team_i_rating_sum = sum(player.approx_posterior.mu for player in team_standings[team_i.team]['players'])
            for player in team_standings[team_i.team]['players']:
                old_mu = player.approx_posterior.mu
                w = 1.
                new_mu = old_mu + w * (team_new_mu - team_i_mu)
                player.update_rating(Rating(new_mu, 0), 0)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            executor.map(_update_player_rating, *zip(*((i+1, team_i) for i, team_i in enumerate(team_ratings))))