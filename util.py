from hearthbreaker.agents.basic_agents import RandomAgent
from hearthbreaker.cards.heroes import hero_for_class
from hearthbreaker.constants import CHARACTER_CLASS, CARD_RARITY
from hearthbreaker.engine import Game, Deck, card_lookup, get_cards
from hearthbreaker.cards import *
from hearthbreaker.cards.base import MinionCard
import random
import timeit
import json
from hearthsql import *
import pdb
import functools
import collections

all_cards = list(get_cards())
database = HearthDatabase('database.sqlite')
def get_random_class():
    return random.randint(1, 9)

@functools.lru_cache(maxsize=None)
def cards_of_class(char_class):
    def filter_class(card):
        return card.character_class == char_class or card.character_class == CHARACTER_CLASS.ALL
    def get_name(card):
        return card.name
    return list(map(get_name, filter(filter_class, all_cards)))

def deck_valid(deck):
    counter = collections.defaultdict(lambda: 0)
    for card in deck.deck:
        card_ob = card_lookup(card)
        rarity = card_ob.rarity
        if card_ob.character_class != 0 and card_ob.character_class != deck.hero:
            return False
        counter[card] += 1
        if rarity == CARD_RARITY.LEGENDARY:
            if not counter[card] == 1:
                return False
        else:
            if not counter[card] <= 2:
                return False
    return True

def can_add(card, deck):
    rarity = card_lookup(card).rarity
    num = deck.count(card)
    if rarity == CARD_RARITY.LEGENDARY:
        return num < 1
    else:
        return num < 2

def replace_card(deck, pos, poss_cards):
    card_ind = random.randint(0, len(poss_cards) - 1)
    to_add = poss_cards[card_ind]
    deck[pos] = to_add
    return

def random_database_deck(group='hearthpwn'):
    deck, hero, id = database.random_deck(group)
    return DeckAndHero(deck, hero, id)

class DeckAndHero:
    def __init__(self, deck, hero, id=None):
        self.deck = deck
        self.hero = hero
        if id:
            self.id = id
        else:
            self.id = database.create_deck(deck, hero)

    @staticmethod
    def from_random(hero=None):
        deck, hero = random_deck(hero)
        return DeckAndHero(deck, hero)

    @staticmethod
    def fromid(id):
        deck, hero = database.get_deck(id)
        return DeckAndHero(deck, hero, id)

    def breakerdeck(self):
        return Deck(list(map(card_lookup, self.deck)), hero_for_class(self.hero))

    def run_game(self, other):
        mydeck = self.breakerdeck()
        game = Game([mydeck, other.breakerdeck()], [RandomAgent(), RandomAgent()])
        tries = 0
        while tries < 10:
            try:
                game.start()
                result = game.players[0].hero.dead and game.players[0].deck == mydeck
                if result:
                    database.create_game('mutational', self.id, other.id, self.id)
                else:
                    database.create_game('mutational', self.id, other.id, other.id)
                return
            except:
                tries += 1
        return True

def evaluate_deck(deck):
    for i in range(10):
        deck.run_game(random_database_deck())

def best_deck(deck1, deck2):
    deck1count = 0
    deck2count = 0
    while deck1count < 2 and deck2count < 2:
        if deck1.run_game(deck2):
            deck1count += 1
        else:
            deck2count += 1
    if deck1count >= 2:
        return deck1
    else:
        return deck2

def occurs(prob):
    return random.random() <= prob

class Tournament:
    # cmp returns true if first arg wins
    def __init__(self, cmp):
        self.cmp = cmp

    def round(self, data):
        last_one = None
        best = []
        for current in data:
            if last_one:
                if cmp(current, last_one):
                    best.append(current)
                else:
                    best.append(last_one)
                last_one = None
        # Check for a by.
        if last_one:
            best.append(last_one)
        return best

    def find_victor(self, data):
        data = list(data)
        while len(data) > 1:
            data = self.round(data)
        return data[0]


class DeckMutator:
    def __init__(self, cross_prob=0.95, mut_rate=0.01, hero=None):
        self.population = [DeckAndHero.from_random(hero) for i in range(3)]
        self.cross_prob = cross_prob
        self.mut_rate = mut_rate
        database.delete_gameset('mutational')

    def get_best(self):
        best = [DeckAndHero.fromid(id) for id in database.best_decks('mutational', 'hearthpwn')]
        def cmp(deck1, deck2):
            while database.get_deck_performance(deck1.id) == database.get_deck_performance(deck2.id):
                evaluate_deck(deck1)
                evaluate_deck(deck2)
        return Tournament(cmp).find_victor(best)

    def prune(self):
        for deck in self.population:
            evaluate_deck(deck)
        self.population = sorted(self.population, key=lambda deck: -1 * database.get_deck_performance(deck.id))[0:len(self.population) // 2]

    def breed(self, deck1, deck2):
        def choose_one(i):
            if occurs(0.5):
                return deck1.deck[i]
            else:
                return deck2.deck[i]
        result = DeckAndHero([choose_one(i) for i in range(30)], deck1.hero)
        self.mutate(result)
        return result

    def mutate(self, deck):
        for i in range(len(deck.deck)):
            if occurs(self.mut_rate):
                replace_card(deck.deck, i, cards_of_class(deck.hero))

    def next_gen(self):
        self.prune()
        def get_random_deck():
            return random.choice(self.population)
        def try_get_next():
            if occurs(self.cross_prob):
                first = get_random_deck()
                second = get_random_deck()
                result = self.breed(first, second)
            else:
                result = get_random_deck()
            return result
        def get_next():
            while True:
                result = try_get_next()
                if deck_valid(result):
                    return result
        self.population = [get_next() for i in range(50)]

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
    #return Deck(list(map(card_lookup, deck_list)), hero_for_class(hero))
    return deck_list, hero

def do_stuff():
    _count = 0

    def play_game():
        def get_deck():
            deck_list, hero = random_deck()
            did = database.create_deck(deck_list, hero)
            return Deck(list(map(card_lookup, deck_list)), hero_for_class(hero)), did

        deck1, did1 = get_deck()
        deck2, did2 = get_deck()
        def submit_result(game):
            if game.players[0] != deck1:
                game.players[0], game.players[1] = game.players[1], game.players[0]
            if game.players[0].deck == deck1 and not game.players[0].hero.dead:
                winner = did1
            else:
                winner = did2
            database.create_game('', did1, did2, winner)

        game = Game([deck1, deck2], [RandomAgent(), RandomAgent()])
        nonlocal _count
        _count += 1
        new_game = game
        try:
            new_game.start()
        except:
            pass

        submit_result(new_game)
        del new_game

        if _count % 1000 == 0:
            print("---- game #{} ----".format(_count))

    print(timeit.timeit(play_game, 'gc.enable()', number=1000) / 1000.0)
command = '''select Card.name, count(*)
            from InDeck, Game, Card
            where InDeck.did = Game.winid and Card.rowid = InDeck.cid
            group by InDeck.cid, Card.name
            order by count(*)'''
#print(database.execute_one(command))
#do_stuff()
#database.init_all()
mut = DeckMutator(mut_rate=0.01)
for i in range(3):
    print('Generation ' + str(i))
    mut.next_gen()
print(mut.get_best().deck)
