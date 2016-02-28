from hearthbreaker.agents.basic_agents import RandomAgent
from hearthbreaker.cards.heroes import hero_for_class
from hearthbreaker.constants import CHARACTER_CLASS, CARD_RARITY
from hearthbreaker.engine import Game, Deck, card_lookup, get_cards
from hearthbreaker.cards import *
from hearthbreaker.cards.base import MinionCard
import random
import timeit
import json

all_cards = list(get_cards())
def get_random_class():
    return random.randint(1, 9)

def cards_of_class(char_class):
    def filter_class(card):
        return card.character_class == char_class or card.character_class == CHARACTER_CLASS.ALL
    def get_name(card):
        return card.name
    return list(map(get_name, filter(filter_class, all_cards)))

def random_deck(hero=None):
    cards_in_deck = dict()
    cards_in_deck.setdefault(0)
    deck_list = list()
    if hero == None:
        hero = get_random_class()
    card_pool = cards_of_class(hero)

    def can_add(card):
        rarity = card_lookup(card).rarity
        num = cards_in_deck.setdefault(card, 0)
        if rarity == CARD_RARITY.LEGENDARY:
            return num < 1
        else:
            return num < 2

    def try_till_card():
        while True:
            card_ind = random.randint(0, len(card_pool) - 1)
            to_add = card_pool[card_ind]
            if can_add(to_add):
                cards_in_deck[to_add] = cards_in_deck.setdefault(to_add, 0) + 1
                return to_add

    for i in range(30):
        deck_list.append(try_till_card())
    return Deck(list(map(card_lookup, deck_list)), hero_for_class(hero))

def do_stuff():
    _count = 0

    def play_game():
        deck1 = random_deck()
        deck2 = random_deck()
        game = Game([deck1, deck2], [RandomAgent(), RandomAgent()])
        nonlocal _count
        _count += 1
        new_game = game
        try:
            new_game.start()
        except Exception as e:
            pass

        del new_game

        if _count % 1000 == 0:
            print("---- game #{} ----".format(_count))

    print(timeit.timeit(play_game, 'gc.enable()', number=1000) / 1000.0)

do_stuff()
