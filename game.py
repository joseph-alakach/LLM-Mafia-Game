import random
import json

from utils import retry
from agent import Agent


class MafiaGame:
    def __init__(self, llm_name: str):
        self.num_players = 10
        self.players = []
        self.roles = ["civilian"] * 6 + ["detective"] + ["mafia"] * 2 + ["don"]
        random.shuffle(self.roles)
        self.llm_name = llm_name
        self.night_count = 0
        self.day_count = 0
        self.game_log = "**Mafia Game Starts**\n"
        self.opinion_log = ""
        self.votes_log = ""
        self.winner_log = ""
        self.alive = [True] * self.num_players
        self.is_detective = False

        mafia_indices = [i for i, role in enumerate(self.roles) if role == "mafia"]
        don_index = next(i for i, role in enumerate(self.roles) if role == "don")

        for i, role in enumerate(self.roles):
            if role in ["mafia", "don"]:
                self.players.append(Agent(
                    llm_name=llm_name,
                    player_name=f"player_{i}",
                    player_role=role,
                    mafia_player_indices=mafia_indices,
                    don_index=don_index
                ))
            else:
                self.players.append(Agent(
                    llm_name=llm_name,
                    player_name=f"player_{i}",
                    player_role=role,
                    mafia_player_indices=[]
                ))

        self.game_data = {
            "game_details": {
                "players": [],
                "mafia_players": [],
                "detective_player": "",
                "game_log": [],
                "game_outcome": {}
            }
        }
        self.game_data["token_details"] = {}
        self.game_data["token_prices"] = {}
        self._initialize_players()

    @classmethod
    def from_llm_list(cls, llm_names: list[str], preassigned_roles: list[str] = None):
        num_players = len(llm_names)
        assert num_players == 10, "This game currently supports exactly 10 players."

        if preassigned_roles:
            assert len(preassigned_roles) == 10, "Need 10 preassigned roles."
            roles = preassigned_roles.copy()
        else:
            roles = ["civilian"] * 6 + ["detective"] + ["mafia"] * 2 + ["don"]
            random.shuffle(roles)

        combined = list(zip(llm_names, roles))
        random.shuffle(combined)
        llm_names, roles = zip(*combined)

        mafia_indices = [i for i, role in enumerate(roles) if role == "mafia"]
        don_index = next(i for i, role in enumerate(roles) if role == "don")

        players = []
        for i in range(num_players):
            role = roles[i]
            llm = llm_names[i]
            if role in ["mafia", "don"]:
                agent = Agent(
                    llm_name=llm,
                    player_name=f"player_{i}",
                    player_role=role,
                    mafia_player_indices=mafia_indices,
                    don_index=don_index
                )
            else:
                agent = Agent(
                    llm_name=llm,
                    player_name=f"player_{i}",
                    player_role=role,
                    mafia_player_indices=[]
                )
            players.append(agent)

        game = cls(llm_name="default_llm")

        game.players = players
        game.roles = roles
        game.num_players = num_players
        game.alive = [True] * num_players

        mafia_players = [player.player_name for player in players if player.role in ["mafia", "don"]]
        detective_player = next((player.player_name for player in players if player.role == "detective"), None)

        game.game_data["game_details"]["players"] = [player.get_player_info() for player in players]
        game.game_data["game_details"]["mafia_players"] = mafia_players
        game.game_data["game_details"]["detective_player"] = detective_player

        return game

    def _initialize_players(self):
        for i, player in enumerate(self.players):
            player_data = player.get_player_info()
            self.game_data["game_details"]["players"].append(player_data)

        mafia_players = [player.player_name for player in self.players if player.role in ["mafia", "don"]]
        self.game_data["game_details"]["mafia_players"] = mafia_players
        self.game_data["game_details"]["detective_player"] = next(
            (player.player_name for player in self.players if player.role == "detective"), None)

    def get_alive_players(self):
        return [i for i, alive in enumerate(self.alive) if alive]

    def night_phase(self):
        print("night_phase")
        self.night_count += 1
        alive_players = self.get_alive_players()
        alive_mafia = [i for i in alive_players if self.roles[i] in ["mafia", "don"]]
        alive_civilians = [i for i in alive_players if self.roles[i] not in ["mafia", "don"]]

        # Don's suspicion (Detective finder)
        don_guess_info = None
        don_index = next((i for i in alive_players if self.roles[i] == "don"), None)
        if don_index is not None and self.is_detective == False:
            guess_index, reason = self.players[don_index].don_guess_detective(
                self.game_log, alive_players, current_night=self.night_count
            )
            actual_detective_index = next((i for i, r in enumerate(self.roles) if r == "detective"), None)
            self.is_detective = (guess_index == actual_detective_index)
            don_guess_info = {
                "night": self.night_count,
                "don_id": self.players[don_index].player_name,
                "guessed_player": f"player_{guess_index}",
                "is_detective": self.is_detective,
                "reason": reason if self.night_count > 1 else None
            }
            if "don_guesses" not in self.game_data["game_details"]:
                self.game_data["game_details"]["don_guesses"] = []

            self.game_data["game_details"]["don_guesses"].append({
                "night": self.night_count,
                "don_id": don_guess_info["don_id"],
                "guessed_player": don_guess_info["guessed_player"],
                "is_detective": don_guess_info["is_detective"],
                "reason": don_guess_info["reason"]
            })

            n =  don_guess_info["night"]
            guessedP = don_guess_info["guessed_player"]
            is_det = don_guess_info["is_detective"]
            for i in alive_mafia:
                self.players[i].don_guesses.append(f"night: {n} - guessed_player_{guessedP} - is_detective? {is_det}")

        # Mafia members vote
        mafia_votes = []
        for i in alive_mafia:
            if self.roles[i] != "don":
                vote = self.players[i].decide_kill(self.game_log, alive_players)
                mafia_votes.append((i, vote))

        # Decide final target
        don_alive = any(self.roles[i] == "don" for i in alive_mafia)
        if don_alive:
            don_index = next(i for i in alive_mafia if self.roles[i] == "don")
            final_target = self.players[don_index].decide_kill(
                self.game_log,
                alive_players,
                mafia_votes=mafia_votes
            )
            mafia_votes.append((don_index, final_target))
        else:
            vote_counts = {}
            for _, vote in mafia_votes:
                vote_counts[vote] = vote_counts.get(vote, 0) + 1

            max_votes = max(vote_counts.values())
            top_choices = [v for v, count in vote_counts.items() if count == max_votes]
            final_target = random.choice(top_choices)

        # Detective investigates
        detective_index = next((i for i in alive_players if self.roles[i] == "detective"), None)
        investigation_result = None
        detective_thinking = None
        if detective_index is not None:
            investigate_target = self.players[detective_index].investigate(self.game_log, alive_players, current_night=self.night_count)
            is_mafia = self.roles[investigate_target] in ["mafia", "don"]
            self.players[detective_index].investigations.append(
                f"player_{investigate_target} - Mafia: {is_mafia}"
            )
            investigation_result = {
                f"player_{detective_index}": {
                    "investigated": f"player_{investigate_target}",
                    "result": is_mafia
                }
            }

            if self.players[detective_index].detective_thinking:
                detective_thinking = {
                    "player_id": self.players[detective_index].player_name,
                    "investigated_player": f"player_{investigate_target}",
                    "internal_reason": self.players[detective_index].detective_thinking[-1]["internal_reason"]
                }
            else:
                detective_thinking = {
                    "player_id": self.players[detective_index].player_name,
                    "investigated_player": f"player_{investigate_target}",
                    "internal_reason": "No reasoning provided yet."
                }

        self.alive[final_target] = False
        self.players[final_target].status = "dead"
        if self.players[final_target].role == "civilian" and self.night_count == 1:
            final_words = ""
            self.game_log += f"\nNight {self.night_count}: Mafia killed player_{final_target}"
        else:
            final_words = self.players[final_target].final_words(self.game_log, cause_of_death="mafia")
            self.game_log += f"\nNight {self.night_count}: Mafia killed player_{final_target}"
            self.game_log += f"\nFinal words from player_{final_target}: {final_words}"

        if hasattr(self, "game_data"):
            mafia_reasons = []
            for mafia_player, vote in mafia_votes:
                if hasattr(self.players[mafia_player], 'mafia_thinking') and self.players[mafia_player].mafia_thinking:
                    mafia_reasons.append({
                        "player_id": self.players[mafia_player].player_name,
                        "vote": f"player_{vote}",
                        "reason": self.players[mafia_player].mafia_thinking[-1]["internal_reason"]
                    })
                else:
                    mafia_reasons.append({
                        "player_id": self.players[mafia_player].player_name,
                        "vote": f"player_{vote}",
                        "reason": "No reasoning provided yet."
                    })

            self.game_data["game_details"]["game_log"].append({
                "night": self.night_count,
                "mafia_kill": f"player_{final_target}",
                "detective_investigation": investigation_result or {},
                "mafia_reasons": mafia_reasons,
                "detective_thinking": detective_thinking,
                "final_words": {
                    "player_id": f"player_{final_target}",
                    "words": final_words
                }
            })

    def day_phase(self):
        print("day_phase")
        self.day_count += 1
        alive_players = self.get_alive_players()

        self.game_log += f"\n\nDay {self.day_count} Begins"
        self.game_data["game_details"]["game_log"].append({
            "day": self.day_count,
            "events": []
        })

        random_start_player = random.choice(alive_players)
        start_index = alive_players.index(random_start_player)

        alive_players = alive_players[start_index:] + alive_players[:start_index]

        for i in alive_players:
            statement = self.players[i].speak_opinion(self.game_log)
            self.opinion_log += f"\nplayer_{i} says: {statement}"
            self.game_log += f"\nplayer_{i} says: {statement}"
            # Add the player's statement to the day's events
            self.game_data["game_details"]["game_log"][-1]["events"].append({
                "player_id": f"player_{i}",
                "statement": statement
            })

        vote_counts = {n: 0 for n in alive_players}
        no_one_votes = 0
        votes_and_reasons = []

        random_start_player = random.choice(alive_players)
        start_index = alive_players.index(random_start_player)

        alive_players = alive_players[start_index:] + alive_players[:start_index]

        for i in alive_players:
            past_votes = "\n".join([f"player_{voter} voted for player_{target}"
                                    for voter, target in votes_and_reasons])
            vote, reason = self.players[i].vote_day(self.game_log, alive_players, past_votes)
            if vote == -1:  # Vote to 'no one'
                no_one_votes += 1
                vote_statement_with_reason = f"player_{i} voted to eliminate no one"
            else:
                vote_counts[vote] += 1
                vote_statement_with_reason = f"player_{i} voted to eliminate player_{vote}"

            votes_and_reasons.append((i, vote))

            self.votes_log += f"\n{vote_statement_with_reason}"
            self.game_log += f"\n{vote_statement_with_reason}"

            self.game_data["game_details"]["game_log"][-1]["events"].append({
                "player_id": f"player_{i}",
                "vote": f"player_{vote}" if vote != -1 else "no one",
                "reason": reason
            })

        most_votes_player = max(vote_counts, key=vote_counts.get)
        sorted_votes = sorted(vote_counts.items(), key=lambda item: item[1], reverse=True)
        top_two = sorted_votes[:2]
        (first_player, first_votes), (second_player, second_votes) = top_two
        if first_votes == second_votes:
            most_votes_count = 0
        else:
            most_votes_count = vote_counts[most_votes_player]

        if most_votes_count <= no_one_votes:  # No one should be eliminated
            self.game_log += "\nNo elimination this round."
            self.game_data["game_details"]["game_log"][-1]["elimination"] = "no elimination this round"
        else:
            self.alive[most_votes_player] = False
            self.players[most_votes_player].status = "dead"
            final_words = self.players[most_votes_player].final_words(self.game_log, cause_of_death="vote")
            self.game_log += f"\nDay: player_{most_votes_player} was voted out by the town/players of the game"
            self.game_log += f"\nFinal words from player_{most_votes_player}: {final_words}"
            # Log in JSON
            self.game_data["game_details"]["game_log"][-1]["elimination"] = f"player_{most_votes_player} was voted out"
            self.game_data["game_details"]["game_log"][-1]["final_words"] = {
                "player_id": f"player_{most_votes_player}",
                "words": final_words
            }

    def check_win_condition(self):
        print("check_win_condition")
        alive_roles = [self.roles[i] for i in self.get_alive_players()]
        mafia_count = sum(1 for r in alive_roles if r in ["mafia", "don"])
        good_count = len(alive_roles) - mafia_count

        if mafia_count == 0:
            self.winner_log = "Good players win!"
            self.game_log += f"\n\n{self.winner_log}"
            self.game_data["game_details"]["game_outcome"] = {
                "winner": "Good players win!",
                "reason": "All Mafia members were eliminated."
            }
            return True
        elif mafia_count >= good_count:
            self.winner_log = "Mafia wins!"
            self.game_log += f"\n\n{self.winner_log}"
            self.game_data["game_details"]["game_outcome"] = {
                "winner": "Mafia wins!",
                "reason": "Mafia outnumbered the good players."
            }
            return True
        return False

    def run(self) -> str:
        while not self.check_win_condition():
            self.night_phase()
            if self.check_win_condition():
                break
            self.day_phase()
        print("\n--- Game Over ---")
        for i, player in enumerate(self.players):
            if self.alive[i]:
                player.status = "alive"
            else:
                player.status = "dead"
            self.game_data["game_details"]["players"][i]["status"] = player.status
            self.game_data["game_details"]["players"][i]["llm_name"] = player.llm_name
            self.game_data["game_details"]["players"][i]["opinion_speech_generation_durations"] = player.opinion_speech_generation_durations
        self.print_token_costs()
        return self.game_log

    def getTokenCountForLLM(self) -> dict:
        llms_used = [player.llm_name for player in self.players]
        llms_used = list(set(llms_used))
        full_usage = {llm_name: {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "full_output_tokens": 0}
                      for llm_name in llms_used}
        for player in self.players:
            llm_name = player.llm_name
            input_tokens = player.input_tokens_used
            output_tokens = player.output_tokens_used
            thinking_tokens = player.thinking_tokens_used
            full_output_tokens = output_tokens + thinking_tokens
            full_usage[llm_name]["input_tokens"] += input_tokens
            full_usage[llm_name]["output_tokens"] += output_tokens
            full_usage[llm_name]["thinking_tokens"] += thinking_tokens
            full_usage[llm_name]["full_output_tokens"] += full_output_tokens
        self.game_data["token_details"] = full_usage
        return full_usage

    def calculate_token_costs(self) -> dict:
        full_usage = self.getTokenCountForLLM()
        pricing = {
            "gemini": {"input": 0.15/1000000, "output": 0.6/1000000, "thinking": 3.5/1000000},
            "openai": {"input": 1.1/1000000, "output": 4.4/1000000, "thinking": 4.4/1000000},
            "claude": {"input": 3/1000000, "output": 15/1000000, "thinking": 15/1000000},
            "grok": {"input": 0.3/1000000, "output": 0.5/1000000, "thinking": 0.5/1000000},
            "deepseek": {"input": 0.14/1000000, "output": 2.19/1000000, "thinking": 2.19/1000000},
        }
        llm_costs = {}
        total_input_cost = 0
        total_output_cost = 0
        total_thinking_cost = 0
        total_full_output_cost = 0
        for llm_name, usage in full_usage.items():
            if llm_name in pricing:
                price_per_token = pricing[llm_name]
                input_cost = usage["input_tokens"] * price_per_token["input"]
                output_cost = usage["output_tokens"] * price_per_token["output"]
                thinking_cost = usage["thinking_tokens"] * price_per_token["thinking"]
                full_output_cost = output_cost + thinking_cost

                llm_costs[llm_name] = {
                    "input_cost": input_cost,
                    "output_cost": output_cost,
                    "thinking_cost": thinking_cost,
                    "full_output_cost": full_output_cost,
                }

                total_input_cost += input_cost
                total_output_cost += output_cost
                total_thinking_cost += thinking_cost
                total_full_output_cost += full_output_cost

        llm_costs["total_costs"] = {
            "total_input_cost": total_input_cost,
            "total_output_cost": total_output_cost,
            "total_thinking_cost": total_thinking_cost,
            "total_full_output_cost": total_full_output_cost,
            "full_total_cost": total_input_cost+total_full_output_cost
        }
        self.game_data["token_prices"] = llm_costs
        return llm_costs

    def print_token_costs(self):
        full_usage = self.getTokenCountForLLM()
        llm_costs = self.calculate_token_costs()

        for llm_name in full_usage:
            print(f"LLM: {llm_name}")
            print(f"{'=' * 50}")
            print(f"Token Count:")
            print(f"  Input Tokens: {full_usage[llm_name]['input_tokens']}")
            print(f"  Output Tokens: {full_usage[llm_name]['output_tokens']}")
            print(f"  Thinking Tokens: {full_usage[llm_name]['thinking_tokens']}")
            print(f"  Full Output Tokens: {full_usage[llm_name]['full_output_tokens']}")

            print(f"Price:")
            print(f"  Input Cost: ${llm_costs[llm_name]['input_cost']:.6f}")
            print(f"  Output Cost: ${llm_costs[llm_name]['output_cost']:.6f}")
            print(f"  Thinking Cost: ${llm_costs[llm_name]['thinking_cost']:.6f}")
            print(f"  Full Output Cost: ${llm_costs[llm_name]['full_output_cost']:.6f}")

            print(f"{'=' * 50}\n")

        print(f"{'=' * 50}")
        print(f"Total Costs for the Run:")
        print(f"  Total Input Cost: ${llm_costs['total_costs']['total_input_cost']:.6f}")
        print(f"  Total Output Cost: ${llm_costs['total_costs']['total_output_cost']:.6f}")
        print(f"  Total Thinking Cost: ${llm_costs['total_costs']['total_thinking_cost']:.6f}")
        print(f"  Total Full Output Cost: ${llm_costs['total_costs']['total_full_output_cost']:.6f}")
        print(f"  Full Total Cost: ${llm_costs['total_costs']['full_total_cost']:.6f}")
        print(f"{'=' * 50}")
