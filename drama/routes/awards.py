from drama.__main__ import app
from drama.helpers.wrappers import *
from drama.helpers.alerts import *
from drama.helpers.get import *
from drama.classes.award import *
from flask import g, jsonify, request


def post_banaward_trigger(post):

    author = post.author
    author.ban(reason="1-day ban award used", days=1)

    send_notification(1046, author, f"Your Drama account has been suspended for a day for [this post]({post.permalink}). It sucked and you should feel bad.")


ACTIONS = {
    "ban": post_banaward_trigger
}


@app.get("/api/awards")
def get_awards():

    return jsonify(list(AWARDS.values()))


@app.put("/api/post/<pid>/awards")
@auth_required
def award_post(pid, v):

    kind = request.form.get("kind", "")

    if kind not in AWARDS:
        return jsonify({"error": "That award doesn't exist."}), 404

    if not v.has_award(kind):
        return jsonify({"error": "You don't have that award."}), 404

    post_award = g.db.query(AwardRelationship).filter(
        and_(
            AwardRelationship.kind == kind,
            AwardRelationship.user_id == v.id
        )
    ).first()

    if post_award.given:
        return jsonify({"error": "You don't have that award."}), 404

    post = get_post(pid)

    if not post:
        return jsonify({"error": "Invalid post ID"}), 404

    post_award.post_id = post.id
    g.db.add(post_award)

    if kind in ACTIONS:
        ACTIONS[kind](post)

    return redirect(post.permalink)
