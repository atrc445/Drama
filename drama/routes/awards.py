from drama.__main__ import app
from drama.helpers.wrappers import *
from drama.helpers.alerts import *
from drama.helpers.get import *
from drama.classes.award import *
from flask import g, jsonify, request


def post_banaward_trigger(post):

    author = post.author
    author.ban(reason="1-day ban award used", days=1)

    send_notification(1, author, f"Your Drama account has been suspended for a day for [this post]({post.permalink}). It sucked and you should feel bad.")


ACTIONS = {
    "ban": post_banaward_trigger
}


@app.get("/api/awards")
@auth_required
def get_awards(v):

    return_value = list(AWARDS.values())

    user_awards = v.awards
    for val in return_value:
        val['owned'] = len([x for x in user_awards if x.kind == val['kind'] and not x.given])

    return jsonify(return_value)


@app.put("/api/post/<pid>/awards")
@auth_required
@validate_formkey
def award_post(pid, v):

    print("sex")

    kind = request.form.get("kind", "")

    if kind not in AWARDS:
        return jsonify({"error": "That award doesn't exist."}), 404

    if not v.has_award(kind):
        return jsonify({"error": "You don't have that award."}), 404

    post_award = g.db.query(AwardRelationship).filter(
        and_(
            AwardRelationship.kind == kind,
            AwardRelationship.user_id == v.id,
            AwardRelationship.submission_id == None,
            AwardRelationship.comment_id == None
        )
    ).first()

    if post_award:
        print(f"award kind {post_award.kind} post id {post_award.submission_id} comment id {post_award.comment_id}")

    if not post_award or post_award.given:
        return jsonify({"error": "You don't have that award."}), 404

    post = g.db.query(Submission).filter_by(id=pid).first()

    if not post:
        return jsonify({"error": "Invalid post ID"}), 404

    print(f"Award post {post.id}")

    post_award.submission_id = post.id
    g.db.add(post_award)

    msg = f"Your [post]({post.permalink}) was given the {AWARDS[kind]['title']} Award!"

    note = request.form.get("note", "")
    if note:
        msg += f"\n\n> {note}"

    send_notification(1, post.author, msg)

    if kind in ACTIONS:
        ACTIONS[kind](post)

    return "", 204
