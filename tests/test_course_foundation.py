import os
import unittest


os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.database import (  # noqa: E402
    init_db,
    SessionLocal,
    DEFAULT_COURSE_ID,
    Course,
    Textbook,
    CanonicalConcept,
    KnowledgeNode,
)
from backend.api.courses import CourseCreate, create_course, delete_course, list_courses  # noqa: E402


class CourseFoundationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(KnowledgeNode).delete()
            db.query(CanonicalConcept).delete()
            db.query(Textbook).delete()
            db.query(Course).filter(Course.id != DEFAULT_COURSE_ID).delete()
            db.commit()
        finally:
            db.close()

    def test_default_course_exists(self):
        db = SessionLocal()
        try:
            course = db.query(Course).filter(Course.id == DEFAULT_COURSE_ID).one()
            self.assertEqual(course.title, "默认课程")
        finally:
            db.close()

    def test_create_and_list_course(self):
        created = create_course(CourseCreate(
            title="医学基础",
            subject="医学",
            default_granularity="core",
        ))
        self.assertEqual(created["title"], "医学基础")
        self.assertTrue(any(item["id"] == created["id"] for item in list_courses("demo_user")))

    def test_delete_course_archives_and_hides_it(self):
        created = create_course(CourseCreate(title="待删除空间"))
        result = delete_course(created["id"])
        self.assertEqual(result["status"], "deleted")
        self.assertFalse(any(item["id"] == created["id"] for item in list_courses("demo_user")))
        db = SessionLocal()
        try:
            archived = db.query(Course).filter(Course.id == created["id"]).one()
            self.assertEqual(archived.status, "archived")
        finally:
            db.close()

    def test_canonical_concept_keeps_source_occurrences_separate(self):
        db = SessionLocal()
        try:
            book_a = Textbook(
                id="book_a",
                course_id=DEFAULT_COURSE_ID,
                filename="a.pdf",
                title="教材 A",
                format="pdf",
            )
            book_b = Textbook(
                id="book_b",
                course_id=DEFAULT_COURSE_ID,
                filename="b.pdf",
                title="教材 B",
                format="pdf",
            )
            concept = CanonicalConcept(
                id="concept_1",
                course_id=DEFAULT_COURSE_ID,
                canonical_name="肺泡通气量",
            )
            db.add_all([book_a, book_b, concept])
            db.flush()
            db.add_all([
                KnowledgeNode(
                    id="node_a",
                    course_id=DEFAULT_COURSE_ID,
                    canonical_concept_id=concept.id,
                    name="肺泡通气量",
                    definition="教材 A 的定义",
                    textbook_id=book_a.id,
                    textbook_title=book_a.title,
                ),
                KnowledgeNode(
                    id="node_b",
                    course_id=DEFAULT_COURSE_ID,
                    canonical_concept_id=concept.id,
                    name="肺泡通气量",
                    definition="教材 B 的定义",
                    textbook_id=book_b.id,
                    textbook_title=book_b.title,
                ),
            ])
            db.commit()

            occurrences = db.query(KnowledgeNode).filter(
                KnowledgeNode.canonical_concept_id == concept.id
            ).all()
            self.assertEqual({node.textbook_id for node in occurrences}, {"book_a", "book_b"})
            self.assertEqual(len(occurrences), 2)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
