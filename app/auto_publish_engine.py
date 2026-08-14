from publication_gate import apply_publication_gate


def should_auto_publish(review, news):
    if not news:
        return False

    publishable, _, _ = apply_publication_gate(news, review)
    return len(publishable) == len(news)
