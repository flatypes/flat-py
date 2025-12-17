import unittest

from flat.py.runtime import *


class TestProducer(unittest.TestCase):
    def test_isla(self) -> None:
        grammar = {
            '<start>': ['<S>'],
            '<S>': ['(<S>)', ''],
        }
        producer = ISLaProducer(grammar)

        for _ in range(10):
            value = producer.produce()
            self.assertTrue(all(c in ['(', ')'] for c in value))
            self.assertTrue(value.count('(') == value.count(')'))

    def test_choice(self) -> None:
        choices = [2, 4, 6]
        producer = ChoiceProducer(choices)

        for _ in range(10):
            value = producer.produce()
            self.assertIn(value, choices)

    def test_choice_complete(self) -> None:
        choices = ['a', 'b', 'c']
        producer = ChoiceProducer(choices)

        covered: dict[object, bool] = {c: False for c in choices}
        for _ in range(3):
            value = producer.produce()
            covered[value] = True

        for c in choices:
            self.assertTrue(covered[c], f"Choice {c} was not produced")

    def test_filter(self) -> None:
        producer = FilterProducer(ChoiceProducer(range(1, 10)), lambda x: x % 2 == 1)

        for _ in range(10):
            value = producer.produce()
            self.assertIn(value, [1, 3, 5, 7, 9])

    def test_union(self) -> None:
        producer = UnionProducer([ChoiceProducer(range(1, 5)), ChoiceProducer(range(6, 10))])

        for _ in range(10):
            value = producer.produce()
            self.assertTrue(value in range(1, 5) or value in range(6, 10))

    def test_tuple(self) -> None:
        producer = TupleProducer([ChoiceProducer(['+', '-']), ChoiceProducer(range(1, 5))])

        for _ in range(10):
            value = producer.produce()
            assert isinstance(value, tuple)
            self.assertTrue(value[0] in ['+', '-'] and value[1] in range(1, 5))

    def test_list(self) -> None:
        producer = ListProducer(ChoiceProducer(['a', 'b']))

        for _ in range(10):
            value = producer.produce()
            assert isinstance(value, list)
            self.assertTrue(all(elem in ['a', 'b'] for elem in value))

    def test_set(self) -> None:
        producer = SetProducer(ChoiceProducer(range(5)))

        for _ in range(10):
            value = producer.produce()
            assert isinstance(value, set)
            self.assertTrue(all(elem in range(5) for elem in value))

    def test_dict(self) -> None:
        producer = DictProducer(ChoiceProducer(['x', 'y']), ChoiceProducer(range(3)))

        for _ in range(10):
            value = producer.produce()
            assert isinstance(value, dict)
            self.assertTrue(all(k in ['x', 'y'] and v in range(3) for k, v in value.items()))
