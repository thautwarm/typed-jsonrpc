from __future__ import annotations

import typing
import types

_T = typing.TypeVar("_T")

Task = typing.Generator[typing.Any, typing.Any, _T]


def wait_until(cond_func: typing.Callable[[], bool]):
    while not cond_func():
        yield
    return 1


def parallel_(*tasklist: Task[typing.Any]):
    m_tasklist = set(tasklist)
    remove_lst: list[Task[typing.Any]] = []
    while m_tasklist:
        for each in m_tasklist:
            try:
                next(each)
            except StopIteration:
                remove_lst.append(each)
        for each in remove_lst:
            m_tasklist.remove(each)
        yield


def parallel_set(tasklist: set[Task[typing.Any]]):
    m_tasklist = tasklist
    remove_lst: list[Task[typing.Any]] = []
    while m_tasklist:
        for each in m_tasklist:
            try:
                next(each)
            except StopIteration:
                remove_lst.append(each)
        for each in remove_lst:
            m_tasklist.remove(each)
        yield

def is_task(x):
    return isinstance(x, types.GeneratorType)


class TaskException(Exception):
    task: Task[typing.Any]
    exc: Exception


def run_once(tasklist: set[Task[typing.Any]]):
    m_tasklist = tasklist
    remove_lst: list[Task[typing.Any]] = []

    for each in m_tasklist:
        try:
            next(each)

        except StopIteration:
            remove_lst.append(each)

        except Exception as e:
            exc = TaskException()
            exc.exc = e
            exc.task = each

    for each in remove_lst:
        m_tasklist.remove(each)

    return remove_lst
