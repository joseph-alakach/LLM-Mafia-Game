import random
from typing import List

import config
import prompts_constants
from token_utils import count_openai_input_tokens, count_openai_output_tokens


class Agent:
    def __init__(self, llm_name: str, player_name: str, player_role: str, mafia_player_indices: List[int]):
        self.llm_name = llm_name
        self.player_name = player_name
        self.role = player_role
        self.input_tokens_used = 0
        self.output_tokens_used = 0
        if self.role  in ["mafia", "don"]:
            self.mafia_players ="These are the mafia players in the game including you " + str([f"player_{i}" for i in mafia_player_indices])
        else:
            self.mafia_players = []

        self.investigations = ""


    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        if self.llm_name == "openai":
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            input_tokens = count_openai_input_tokens(messages, model=config.OPENAI_MODEL)
            llm_response = config.OPENAI_MODEL.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=messages,
                temperature=0.3,
            )
            output_text = llm_response.choices[0].message.content.strip()
            output_tokens = count_openai_output_tokens(output_text, model=config.OPENAI_MODEL)

            self.input_tokens_used += input_tokens
            self.output_tokens_used += output_tokens
            return output_text
        else:
            raise NotImplementedError(f"LLM {self.llm_name} not supported yet.")

    def _build_system_prompt(self):
        rules = prompts_constants.SYSTEM_PROMPTS["rules"]
        role_prompt = prompts_constants.SYSTEM_PROMPTS.get(self.role, "")
        return f"{rules}\n\n{role_prompt}\n\nYou are {self.player_name}. Your role is {self.role}. {self.mafia_players}"

    def speak_opinion(self, game_log: str) -> str:
        system_prompt = self._build_system_prompt()
        user_prompt = (
            f"Here is what happened in the game so far:\n{game_log}\n\n"
            "Now it's the DAY phase. Please express your thoughts and suspicions about who could be Mafia. "
            "Keep it short, logical, and persuasive. Return only your statement."
        )
        return self._call_llm(system_prompt, user_prompt)

    def vote_day(self, game_log: str, nominees: list[int]) -> tuple:
        nominee_names = [f"player_{i}" for i in nominees]
        system_prompt = self._build_system_prompt()
        user_prompt = (
            f"Here is what happened in the game so far:\n{game_log}\n\n"
            f"The following players are nominated for elimination: {', '.join(nominee_names)}.\n"
            "Choose who you want to eliminate and explain your reasoning.\n\n"
            "Format:\nplayer_#\n\"Reason\"\n"
        )
        response = self._call_llm(system_prompt, user_prompt)
        try:
            lines = response.split("\n", 1)
            voted_player = int(lines[0].replace("player_", "").strip())
            reason = lines[1].strip() if len(lines) > 1 else "No reason provided"
            return voted_player, reason
        except Exception as e:
            print(f"[vote_day error] {e}")
            return nominees[0], "Fallback vote due to parsing error."

    def investigate(self, game_log: str, alive_players: list[int]) -> int:
        possible_targets = [p for p in alive_players if f"player_{p}" != self.player_name]
        system_prompt = self._build_system_prompt()
        user_prompt = (
            f"Here is what happened in the game so far:\n{game_log}\n\n"
            "You are the Detective. Choose one player to investigate tonight.\n"
            f"The investigation you did so far: \n{self.investigations}"
            f"Alive players: {', '.join(f'player_{i}' for i in possible_targets)}\n"
            "Return only their name in this format: player_#"
        )
        response = self._call_llm(system_prompt, user_prompt)
        try:
            return int(response.replace("player_", "").strip())
        except:
            return random.choice(possible_targets)

    def decide_kill(self, game_log: str, candidates: list[int]) -> int:
        possible_targets = [f"player_{i}" for i in candidates]
        system_prompt = self._build_system_prompt()
        user_prompt = (
            f"Here is what happened in the game so far:\n{game_log}\n\n"
            f"As a Mafia/Don, you must choose who to kill tonight.\n"
            f"Candidates: {', '.join(possible_targets)}\n"
            "Return only one player name in this format: player_#"
        )
        response = self._call_llm(system_prompt, user_prompt)
        try:
            return int(response.replace("player_", "").strip())
        except:
            return candidates[0]
