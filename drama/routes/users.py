import qrcode
import io
from datetime import datetime
import time

from drama.classes.user import ViewerRelationship
from drama.helpers.alerts import *
from drama.helpers.sanitize import *
from drama.helpers.markdown import *
from drama.mail import *
from flask import *
from drama.__main__ import app, cache, limiter, db_session
from pusher_push_notifications import PushNotifications

PUSHER_KEY = environ.get("PUSHER_KEY", "").strip()

beams_client = PushNotifications(
		instance_id='02ddcc80-b8db-42be-9022-44c546b4dce6',
		secret_key=PUSHER_KEY,
)

@app.post("/@<username>/suicide")
@auth_required
def suicide(v, username):
	t = int(time.time())
	if v.admin_level == 0 and t - v.suicide_utc < 86400: return "", 204
	user = get_user(username)
	suicide = f"Hi there,\n\nA [concerned dramatard]({v.permalink}) reached out to us about you.\n\nWhen you're in the middle of something painful, it may feel like you don't have a lot of options. But whatever you're going through, you deserve help and there are people who are here for you.\n\nThere are resources available in your area that are free, confidential, and available 24/7:\n\n- Call, Text, or Chat with Canada's [Crisis Services Canada](https://www.crisisservicescanada.ca/en/)\n- Call, Email, or Visit the UK's [Samaritans](https://www.samaritans.org/)\n- Text CHAT to America's [Crisis Text Line](https://www.crisistextline.org/) at 741741.\nIf you don't see a resource in your area above, the moderators at r/SuicideWatch keep a comprehensive list of resources and hotlines for people organized by location. Find Someone Now\n\nIf you think you may be depressed or struggling in another way, don't ignore it or brush it aside. Take yourself and your feelings seriously, and reach out to someone.\n\nIt may not feel like it, but you have options. There are people available to listen to you, and ways to move forward.\n\nYour fellow dramatards care about you and there are people who want to help."
	send_notification(1046, user, suicide)
	v.suicide_utc = t
	g.db.add(v)
	return "", 204

@app.route("/api/v1/user/<username>", methods=["GET"])
@auth_desired
@api("read")
def user_info(v, username):
	user = get_user(username, v=v)
	return jsonify(user.json)

@app.route("/leaderboard", methods=["GET"])
@auth_desired
def leaderboard(v):
	if v and v.is_banned and not v.unban_utc:return render_template("seized.html")
	users = g.db.query(User).options(lazyload('*'))
	users1= sorted(users, key=lambda x: x.dramacoins, reverse=True)[:25]
	users2= list(users.order_by(User.stored_subscriber_count).limit(10).all())
	return render_template("leaderboard.html", v=v, users1=users1, users2=users2)

@app.get("/@<username>/css")
def get_css(username):
	user = get_user(username)
	if user.css: css = user.css
	else: css = ""
	resp=make_response(css)
	resp.headers.add("Content-Type", "text/css")
	return resp

@app.get("/@<username>/profilecss")
def get_profilecss(username):
	user = get_user(username)
	if user.profilecss: profilecss = user.profilecss
	else: profilecss = ""
	resp=make_response(profilecss)
	resp.headers.add("Content-Type", "text/css")
	return resp

@app.route("/@<username>/reply/<id>", methods=["POST"])
@auth_required
def messagereply(v, username, id):
	message = request.form.get("message", "")[:1000].strip()
	user = get_user(username)
	message = message.replace("\n", "\n\n")
	with CustomRenderer() as renderer: text_html = renderer.render(mistletoe.Document(message))
	text_html = sanitize(text_html, linkgen=True)
	parent = get_comment(int(id), v=v)
	new_comment = Comment(author_id=v.id,
							parent_submission=None,
							parent_fullname=parent.fullname,
							parent_comment_id=id,
							level=parent.level + 1,
							sentto=user.id
							)
	g.db.add(new_comment)
	g.db.flush()
	new_aux = CommentAux(id=new_comment.id, body=message, body_html=text_html)
	g.db.add(new_aux)
	notif = Notification(comment_id=new_comment.id, user_id=user.id)
	g.db.add(notif)
	g.db.commit()
	return redirect('/notifications?all=true')

@app.route("/songs/<id>", methods=["GET"])
def songs(id):
	try: id = int(id)
	except: return '', 400
	user = g.db.query(User).filter_by(id=id).first()
	return send_from_directory('/songs/', f'{user.song}.mp3')

@app.route("/subscribe/<post_id>", methods=["POST"])
@auth_required
def subscribe(v, post_id):
	new_sub = Subscription(user_id=v.id, submission_id=post_id)
	g.db.add(new_sub)
	g.db.commit()
	return "", 204
	
@app.route("/unsubscribe/<post_id>", methods=["POST"])
@auth_required
def unsubscribe(v, post_id):
	sub=g.db.query(Subscription).filter_by(user_id=v.id, submission_id=post_id).first()
	g.db.delete(sub)
	return "", 204

@app.route("/@<username>/message", methods=["POST"])
@auth_required
def message2(v, username):
	user = get_user(username, v=v)
	if user.is_blocking: return jsonify({"error": "You're blocking this user."}), 403
	if user.is_blocked: return jsonify({"error": "This user is blocking you."}), 403
	message = request.form.get("message", "")[:1000].strip()
	send_pm(v.id, user, message)
	beams_client.publish_to_interests(
		interests=[str(user.id)],
		publish_body={
			'web': {
				'notification': {
					'title': f'New message from @{v.username}',
					'body': message,
					'deep_link': f'https://rdrama.net/notifications',
				},
			},
		},
	)
	return redirect('/notifications?all=true')

@app.route("/2faqr/<secret>", methods=["GET"])
@auth_required
def mfa_qr(secret, v):
	x = pyotp.TOTP(secret)
	qr = qrcode.QRCode(
		error_correction=qrcode.constants.ERROR_CORRECT_L
	)
	qr.add_data(x.provisioning_uri(v.username, issuer_name="Drama"))
	img = qr.make_image(fill_color="#000000", back_color="white")

	mem = io.BytesIO()

	img.save(mem, format="PNG")
	mem.seek(0, 0)
	return send_file(mem, mimetype="image/png", as_attachment=False)


@app.route("/api/is_available/<name>", methods=["GET"])
@app.route("/api/v1/is_available/<name>", methods=["GET"])
@auth_desired
@api("read")
def api_is_available(name, v):

	name=name.strip()

	if len(name)<3 or len(name)>25:
		return jsonify({name:False})
		
	name=name.replace('_','\_')

	x= g.db.query(User).options(
		lazyload('*')
		).filter(
		or_(
			User.username.ilike(name),
			User.original_username.ilike(name)
			)
		).first()

	if x:
		return jsonify({name: False})
	else:
		return jsonify({name: True})


@app.route("/id/<id>", methods=["GET"])
def user_id(id):

	user = get_account(int(id))
	return redirect(user.permalink)

# Allow Id of user to be queryied, and then redirect the bot to the
# actual user api endpoint.
# So they get the data and then there will be no need to reinvent
# the wheel.
@app.route("/api/v1/uid/<uid>", methods=["GET"])
@auth_desired
@api("read")
def user_by_uid(uid, v=None):
	user=get_account(uid)
	
	return redirect(f'/api/v1/user/{user.username}/info')
		
@app.route("/u/<username>", methods=["GET"])
def redditor_moment_redirect(username):
	return redirect(f"/@{username}")

@app.route("/@<username>/followers", methods=["GET"])
@auth_required
def followers(username, v):
	if v and v.is_banned and not v.unban_utc: return render_template("seized.html")

	u = get_user(username, v=v)
	users = [x.user for x in u.followers]
	return render_template("followers.html", v=v, u=u, users=users)

@app.get("/views")
@auth_required
def visitors(v):
	if v.admin_level < 1 and not v.patron: return render_template("errors/patron.html", v=v)
	viewers=sorted(v.viewers, key = lambda x: x.last_view_utc, reverse=True)
	return render_template("viewers.html", v=v, viewers=viewers)

@app.route("/@<username>", methods=["GET"])
@app.route("/api/v1/user/<username>/listing", methods=["GET"])
@auth_desired
@public("read")
def u_username(username, v=None):
	if v and v.is_banned and not v.unban_utc: return render_template("seized.html")

	# username is unique so at most this returns one result. Otherwise 404

	# case insensitive search

	u = get_user(username, v=v)

	# check for wrong cases

	if username != u.username:
		return redirect(request.path.replace(username, u.username))

	if u.reserved:
		return {'html': lambda: render_template("userpage_reserved.html",
												u=u,
												v=v),
				'api': lambda: {"error": f"That username is reserved for: {u.reserved}"}
				}

	# viewers
	if v and u.id != v.id:
		view = g.db.query(ViewerRelationship).filter(
			and_(
				ViewerRelationship.viewer_id == v.id,
				ViewerRelationship.user_id == u.id
			)
		).first()

		if view:
			view.last_view_utc = g.timestamp
		else:
			view = ViewerRelationship(user_id = u.id,
									  viewer_id = v.id)

		g.db.add(view)

	if u.is_private and (not v or (v.id != u.id and v.admin_level < 3)):
		return {'html': lambda: render_template("userpage_private.html",
												u=u,
												v=v),
				'api': lambda: {"error": "That userpage is private"}
				}

	if u.is_blocking and (not v or v.admin_level < 3):
		return {'html': lambda: render_template("userpage_blocking.html",
												u=u,
												v=v),
				'api': lambda: {"error": f"You are blocking @{u.username}."}
				}

	if u.is_blocked and (not v or v.admin_level < 3):
		return {'html': lambda: render_template("userpage_blocked.html",
												u=u,
												v=v),
				'api': lambda: {"error": "This person is blocking you."}
				}

	sort = request.args.get("sort", "new")
	t = request.args.get("t", "all")
	page = int(request.args.get("page", "1"))
	page = max(page, 1)

	ids = u.userpagelisting(v=v, page=page, sort=sort, t=t)

	# we got 26 items just to see if a next page exists
	next_exists = (len(ids) == 26)
	ids = ids[0:25]

   # If page 1, check for sticky
	if page == 1:
		sticky = []
		sticky = g.db.query(Submission).filter_by(is_pinned=True, author_id=u.id).all()
		if sticky:
			for p in sticky:
				ids = [p.id] + ids

	listing = get_posts(ids, v=v)

	if u.unban_utc:
		unban = datetime.fromtimestamp(u.unban_utc).strftime('%c')
		return {'html': lambda: render_template("userpage.html",
												unban=unban,
												u=u,
												v=v,
												listing=listing,
												page=page,
												sort=sort,
												t=t,
												next_exists=next_exists,
												is_following=(v and u.has_follower(v))),
				'api': lambda: jsonify({"data": [x.json for x in listing]})
				}

	return {'html': lambda: render_template("userpage.html",
										u=u,
										v=v,
										listing=listing,
										page=page,
										sort=sort,
										t=t,
										next_exists=next_exists,
										is_following=(v and u.has_follower(v))),
		'api': lambda: jsonify({"data": [x.json for x in listing]})
		}


@app.route("/@<username>/comments", methods=["GET"])
@app.route("/api/v1/user/<username>/comments", methods=["GET"])
@auth_desired
@public("read")
def u_username_comments(username, v=None):
	if v and v.is_banned and not v.unban_utc: return render_template("seized.html")

	# username is unique so at most this returns one result. Otherwise 404

	# case insensitive search

	user = get_user(username, v=v)

	# check for wrong cases

	if username != user.username: return redirect(f'{user.url}/comments')

	u = user

	if u.reserved:
		return {'html': lambda: render_template("userpage_reserved.html",
												u=u,
												v=v),
				'api': lambda: {"error": f"That username is reserved for: {u.reserved}"}
				}

	if u.is_private and (not v or (v.id != u.id and v.admin_level < 3)):
		return {'html': lambda: render_template("userpage_private.html",
												u=u,
												v=v),
				'api': lambda: {"error": "That userpage is private"}
				}

	if u.is_blocking and (not v or v.admin_level < 3):
		return {'html': lambda: render_template("userpage_blocking.html",
												u=u,
												v=v),
				'api': lambda: {"error": f"You are blocking @{u.username}."}
				}

	if u.is_blocked and (not v or v.admin_level < 3):
		return {'html': lambda: render_template("userpage_blocked.html",
												u=u,
												v=v),
				'api': lambda: {"error": "This person is blocking you."}
				}

	page = int(request.args.get("page", "1"))
	sort=request.args.get("sort","new")
	t=request.args.get("t","all")

	ids = user.commentlisting(
		v=v, 
		page=page,
		sort=sort,
		t=t,
		)

	# we got 26 items just to see if a next page exists
	next_exists = (len(ids) == 26)
	ids = ids[0:25]

	listing = get_comments(ids, v=v)

	is_following = (v and user.has_follower(v))

	return {"html": lambda: render_template("userpage_comments.html",
											u=user,
											v=v,
											listing=listing,
											page=page,
											sort=sort,
											t=t,
											next_exists=next_exists,
											is_following=is_following,
											standalone=True),
			"api": lambda: jsonify({"data": [c.json for c in listing]})
			}

@app.route("/api/v1/user/<username>/info", methods=["GET"])
@auth_desired
@public("read")
def u_username_info(username, v=None):

	user=get_user(username, v=v)

	if user.is_blocking:
		return jsonify({"error": "You're blocking this user."}), 401
	elif user.is_blocked:
		return jsonify({"error": "This user is blocking you."}), 403

	return jsonify(user.json)


@app.route("/api/follow/<username>", methods=["POST"])
@auth_required
def follow_user(username, v):

	target = get_user(username)

	if target.id==v.id:
		return jsonify({"error": "You can't follow yourself!"}), 400

	# check for existing follow
	if g.db.query(Follow).filter_by(user_id=v.id, target_id=target.id).first():
		abort(409)

	new_follow = Follow(user_id=v.id,
						target_id=target.id)

	g.db.add(new_follow)
	target.stored_subscriber_count = g.db.query(Follow).filter_by(target_id=target.id)
	g.db.add(target)

	existing = g.db.query(Notification).filter_by(followsender=v.id, user_id=target.id).first()
	if not existing: send_follow_notif(v.id, target.id, f"@{v.username} has followed you!")
	return "", 204


@app.route("/api/unfollow/<username>", methods=["POST"])
@auth_required
def unfollow_user(username, v):

	target = get_user(username)

	# check for existing follow
	follow = g.db.query(Follow).filter_by(
		user_id=v.id, target_id=target.id).first()

	if not follow:
		abort(409)

	g.db.delete(follow)
	target.stored_subscriber_count = g.db.query(Follow).filter_by(target_id=target.id)
	g.db.add(target)

	existing = g.db.query(Notification).filter_by(followsender=v.id, user_id=target.id).first()
	if not existing: send_unfollow_notif(v.id, target.id, f"@{v.username} has unfollowed you!")
	return "", 204


@app.route("/@<username>/pic/profile")
@limiter.exempt
def user_profile(username):
	x = get_user(username)
	return redirect(x.profile_url)

@app.route("/uid/<uid>/pic/profile")
@limiter.exempt
def user_profile_uid(uid):
	x=get_account(uid)
	return redirect(x.profile_url)


@app.route("/@<username>/saved/posts", methods=["GET"])
@app.route("/api/v1/saved/posts", methods=["GET"])
@auth_required
@api("read")
def saved_posts(v, username):

	page=int(request.args.get("page",1))

	ids=v.saved_idlist(page=page)

	next_exists=len(ids)==26

	ids=ids[0:25]

	listing = get_posts(ids, v=v)

	return {'html': lambda: render_template("userpage.html",
											u=v,
											v=v,
											listing=listing,
											page=page,
											next_exists=next_exists,
											),
			'api': lambda: jsonify({"data": [x.json for x in listing]})
			}


@app.route("/@<username>/saved/comments", methods=["GET"])
@app.route("/api/v1/saved/comments", methods=["GET"])
@auth_required
@api("read")
def saved_comments(v, username):

	page=int(request.args.get("page",1))

	ids=v.saved_comment_idlist(page=page)

	next_exists=len(ids)==26

	ids=ids[0:25]

	listing = get_comments(ids, v=v, sort="new")


	return {'html': lambda: render_template("userpage_comments.html",
											u=v,
											v=v,
											listing=listing,
											page=page,
											next_exists=next_exists,
											standalone=True),
			'api': lambda: jsonify({"data": [x.json for x in listing]})
			}
