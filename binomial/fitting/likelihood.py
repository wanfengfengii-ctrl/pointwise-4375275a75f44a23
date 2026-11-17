import math


def expit(value):
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def binomial_log_likelihood(n, k, probabilities):
    total = 0.0
    for trials, successes, p in zip(n, k, probabilities):
        if not 0 <= p <= 1:
            raise ValueError("invalid probability")
        if (p == 0 and successes) or (p == 1 and successes != trials):
            return -math.inf
        if successes:
            total += successes * math.log(p)
        if trials != successes:
            total += (trials - successes) * math.log1p(-p)
    return total


def score_and_information(a, n, k, theta):
    dimension = len(theta)
    probabilities = tuple(expit(math.fsum(float(x) * b for x, b in zip(row, theta))) for row in a)
    score = tuple(math.fsum(float(row[j]) * (successes - trials * p)
                            for row, trials, successes, p in zip(a, n, k, probabilities))
                  for j in range(dimension))
    information = tuple(tuple(math.fsum(
        float(row[j]) * float(row[l]) * trials * p * (1 - p)
        for row, trials, p in zip(a, n, probabilities))
        for l in range(dimension)) for j in range(dimension))
    return probabilities, score, information
