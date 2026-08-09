from verification import passes_publish_safety


def should_auto_publish(review, news):
    if not review.get("ok"):
        return False

    if not news:
        return False

    return all(passes_publish_safety(item) for item in news)
