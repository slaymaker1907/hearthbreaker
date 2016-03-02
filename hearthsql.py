import sqlite3
from hearthbreaker.engine import get_cards
import html.parser as html
import re
import requests
import pdb
import hearthbreaker.constants as consts
import functools
import collections
import threading

def get_card_count(cards):
    result = collections.defaultdict(lambda: 0)
    for card in cards:
        result[card] += 1
    return result

class MaxPageNumber(html.HTMLParser):
    def __init__(self):
        super().__init__()
        self.max = 1
        self.record = False

    def handle_starttag(self, tag, attrs):
        try:
            if attrs[1][1] == 'b-pagination-item':
                self.record = True
        except:
            pass

    def handle_endtag(self, tag):
        if self.record:
            self.record = False

    def handle_data(self, data):
        if self.record:
            data = int(data)
            if data > self.max:
                self.max = data

class NextPage(html.HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = None
        self.record = False

    def handle_starttag(self, tag, attrs):
        try:
            if attrs[1][0] == 'rel' and tag == 'a' and attrs[1][1] == 'next':
                self.result = attrs[0][1]
        except:
            pass

class LinkParser(html.HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self.save_data = False
        self.next_link = False

    def check_for_attr(self, attrs, ekey, evalue):
        for key, value in attrs:
            if key == ekey and evalue == value:
                return True

    def get_attr(self, attrs, ekey):
        for key, value in attrs:
            if key == ekey:
                return value

    def handle_starttag(self, tag, attrs):
        if tag == 'td' and self.check_for_attr(attrs, 'class', 'col-class'):
            self.save_data = True
        if tag == 'span' and self.check_for_attr(attrs, 'class', 'tip'):
            self.next_link = True
        if self.next_link and tag == 'a':
            self.link = self.get_attr(attrs, 'href')
            self.next_link = False

    def handle_endtag(self, tag):
        if tag == 'td' and self.save_data:
            self.save_data = False

    def handle_data(self, data):
        if self.save_data:
            self.result.append((self.link, data))

    def parse_html(self, html):
        self.feed(html)
        self.close()
        return self.result

class CockatriceParser(html.HTMLParser):
    def __init__(self):
        super().__init__()
        self.save_data = False
        self.result = ''
        self.expected_tag = 'textarea'
    def handle_starttag(self, tag, attrs):
        if tag == self.expected_tag:
            self.save_data = True
    def handle_endtag(self, tag):
        if tag == self.expected_tag:
            self.save_data = False
    def handle_data(self, data):
        self.result += data

    def parse_cockatrice(self, html):
        self.feed(html)
        self.close()
        matches = re.finditer(r'([12]) (.*)\r', self.result)
        result = []
        for match in matches:
            card = match.group(2)
            result.append(card)
            if (match.group(1) == '2'):
                result.append(card)
        return result

class HearthDatabase:
    def __init__(self, filename):
        self.filename = filename
        self.lock = threading.Lock()

    def execute(self, *commands):
        with self.lock:
            conn = sqlite3.connect(self.filename)
            result = []
            with conn:
                for command in commands:
                    result.append(list(conn.execute(command)))
            conn.close()
        return result

    def execute_one(self, command):
        return self.execute(command)[0]

    def init_card_tables(self):
        create_card = '''create table 'Card'
                         (name VARCHAR(255) NOT NULL,
                         mana INT NOT NULL,
                         rare VARCHAR(30) NOT NULL,
                         class INT NOT NULL)
                         '''
        create_minion = '''create table 'Minion'
                            (cid ROWID,
                            attack INT,
                            health INT,
                            primary key (cid),
                            foreign key (cid) references Card(rowid))'''
        create_weapon = '''create table 'Weapon'
                            (cid ROWID,
                            attack INT,
                            dura INT,
                            primary key (cid),
                            foreign key (cid) references Card(rowid))'''
        self.execute(create_card, create_minion, create_weapon)

    def init_deck_tables(self):
        create_deck = '''create table 'Deck'
                        (
                        class int NOT NULL,
                        grouping VARCHAR(255) NOT NULL
                        )'''
        create_game = '''create table 'Game'
                        (
                        setname VARCHAR(255) NOT NULL,
                        player1 INT NOT NULL,
                        player2 INT NOT NULL,
                        winid INT NOT NULL,
                        foreign key (winid) references Deck(id),
                        foreign key (player1) references Deck(id),
                        foreign key (player2) references Deck(id)
                        )'''
        create_collection = "create table 'Collection' (name VARCHAR(255), primary key (name))"
        create_incol = '''create table 'InCollection'
                            (cid ROWID,
                            colname VARCHAR(255),
                            primary key (cid, colname),
                            foreign key (cid) references Card(rowid),
                            foreign key (colname) references Collection(name)
                            )'''
        create_indeck = '''create table 'InDeck'
                            (did ROWID,
                            cid ROWID,
                            occurs INT,
                            primary key(did, cid)
                            foreign key (did) references Deck(rowid),
                            foreign key (cid) references Card(rowid)
                            )'''
        self.execute(create_deck, create_game, create_collection, create_incol, create_indeck)

    def init_all(self):
        self.init_card_tables()
        self.init_deck_tables()
        self.init_cardlist()

    def all_cards(self):
        self.execute_one('select rowid, name, mana, rare, class from Card')

    def escape_name(self, name):
        return name

    def init_cardlist(self):
        all_cards = list(get_cards())
        def card_to_sql(card):
            result = '("{name}", {mana}, {rare}, {char_class})'.format(name=card.name, mana=card.mana,
                rare=card.rarity, char_class=card.character_class)
            return result
        values_str = ', '.join(map(card_to_sql, all_cards))
        command = 'insert into Card (name, mana, rare, class) values {0}'.format(values_str)
        self.execute(command)

    def card_pred(self, cards):
        def deck_card_sql(card_name):
            card_name = self.escape_name(card_name)
            return 'Card.name = "{card_name}"'.format(card_name=card_name)
        return ' or '.join([deck_card_sql(name) for name in cards])

    def create_deck(self, card_names, char_class, group=''):
        with self.lock:
            conn = sqlite3.connect(self.filename)
            cursor = conn.cursor()
            get_ids = 'select name, rowid from Card where ' + self.card_pred(card_names)
            idlookup = {name:rowid for name, rowid in cursor.execute(get_ids)}
            try:
                assert functools.reduce(lambda bool1, bool2: bool1 or bool2, map(lambda name: name in idlookup, card_names), True)
                card_count = get_card_count(card_names)
                create_deck = 'insert into Deck (class, grouping) values ({0}, "{1}")'.format(char_class, group)
                cursor.execute(create_deck)
                deckid = cursor.lastrowid
                values = ['({did}, {cid}, {occurs})'.format(did=deckid, cid=idlookup[name], occurs=count) for name, count in card_count.items()]
                values = ', '.join(values)
                command = 'insert into InDeck (did, cid, occurs) values ' + values
                cursor.execute(command)
                conn.commit()
            finally:
                conn.close()
            return deckid

    def get_deck(self, deckid):
        command = '''select name, occurs from InDeck inner join Card on InDeck.cid = Card.rowid where InDeck.did={0}'''.format(deckid)
        char_class = '''select class from Deck where rowid={0}'''.format(deckid)
        result = self.execute(command, char_class)
        return self.format_deck(result[0]), int(result[1][0][0])

    def create_game(self, setname, deck1, deck2, winid):
        command = '''insert into Game (setname, player1, player2, winid)
                    values ("{0}", {1}, {2}, {3})'''.format(setname, deck1, deck2, winid)
        self.execute(command)

    def best_decks(self, gameset, not_group):
        command = '''select Game.winid from Game inner join Deck on Game.winid = Deck.rowid
                    where Game.setname = "{0}" and Deck.grouping <> "{1}"
                    group by Game.winid having
                    1.0*count(*)/(select count(*) from Game as g where g.player1=Game.winid or g.player2=Game.winid)
                     = (select max(1.0*c/all) from (
                    select count(*) as c
                    from Game as game2 INNER JOIN Deck as deck2 on game2.winid = deck2.rowid
                    where game2.setname = "{0}" and deck2.grouping <> "{1}"
                    group by game2.winid) as f,(
                        select count(*) from
                    ) as g)'''.format(gameset, not_group)
        return self.execute(command)[0][0]


    def random_deck(self, group):
        command = 'select rowid, class from Deck where grouping="{0}" order by RANDOM() limit 1'.format(group)
        result = self.execute_one(command)
        rowid = str(result[0][0])
        char_class = result[0][1]
        command = 'select name, occurs from InDeck inner join Card on cid=Card.rowid where did=' + rowid
        result = list(self.execute_one(command))
        return self.format_deck(result), int(char_class), int(rowid)

    def format_deck(self, sql):
        deck = []
        for cardob in sql:
            card = cardob[0]
            deck.append(card)
            if cardob[1] == 2:
                deck.append(card)
        assert len(deck) == 30
        return deck

    def get_deck_performance(self, deckid):
        total_games = '''select COUNT(*) from Game where player1={0} or player2={0}'''.format(deckid)
        won_games = '''select COUNT(*) from Game where winid={0}'''.format(deckid)
        result = self.execute(total_games, won_games)
        return result[1][0][0] / result[0][0][0]

    def cards_for_class(self, char_class):
        return self.execute_one('select rowid, name, mana, rare, class from Card where class=0 or class={0}'.format(char_class))

    def delete_gameset(self, setname):
        self.execute('delete from Game where setname="{0}"'.format(setname), 'vacuum')

    def parse_hearthpwn_decks(self):
        http_sema = threading.BoundedSemaphore(value=6)
        def make_request(to_get):
            with http_sema:
                return requests.get(to_get).text
        def get_deck_from_num(num):
            url = 'http://www.hearthpwn.com/decks/{num}/export/1'.format(num=num)
            html = make_request(url)
            return CockatriceParser().parse_cockatrice(html)
        def get_decks_page(pagenum):
            return 'http://www.hearthpwn.com/decks?filter-is-forge=2&filter-deck-tag=1&filter-set-loe-min=0&filter-set-loe-max=0&filter-set-tgt-min=0&filter-set-tgt-max=0&sort=datemodified&page=' + str(pagenum)
        def get_next_link(html):
            parser = NextPage()
            parser.feed(html)
            parser.close()
            return parser.result
        def extract_nums(link):
            return re.match('/decks/(\d+)', link).group(1)
        def process_deck(deck, hero):
            try:
                deck = get_deck_from_num(deck)
                if len(deck) != 30:
                    raise Exception('Deck must have 30 cards:' + str(len(deck)))
                hero = consts.CHARACTER_CLASS.from_str(hero)
                self.create_deck(deck, hero, 'hearthpwn')
            except AssertionError:
                raise
            except Exception as e:
                print('Exception:' + str(e))
        link = get_decks_page(1)
        def process_link(link):
            html = make_request(link)
            to_search = [(extract_nums(link),charclass) for link, charclass in LinkParser().parse_html(html)]
            for deck, hero in to_search:
                process_deck(deck, hero)
        maxer = MaxPageNumber()
        maxer.feed(requests.get(link).text)
        maxer.close
        links = [get_decks_page(i) for i in range(maxer.max)]
        threads = [threading.Thread(target=lambda: process_link(link)) for link in links]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        '''
        while link != None:
            print('Current link:' + str(link))
            html = requests.get(link).text
            to_search = [(extract_nums(link),charclass) for link, charclass in LinkParser().parse_html(html)]
            for deck, hero in to_search:
                process_deck(deck, hero)
            try:
                link = 'http://www.hearthpwn.com' + get_next_link(html)
            except:
                link = None
        '''

#database = HearthDatabase('database.sqlite')
#database.init_all()
#database.parse_hearthpwn_decks()
#best_decks = database.best_decks('mutational', 'hearthpwn')
#print([database.get_deck(did) for did in best_decks])
#print(len(database.random_deck('hearthpwn')[0]))
