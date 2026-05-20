module.exports = app => {
    const groups = require("../controllers/groups.controller.js");

    var router = require("express").Router();

    // Create a new Tutorial
    router.post("/", groups.create);

    // Retrieve all groups
    router.get("/", groups.findAll);

    // Retrieve a single Tutorial with id
    router.get("/:id", groups.findOne);

    // Update a Tutorial with id
    router.put("/:id", groups.update);

    // Delete a Tutorial with id
    router.delete("/:id", groups.delete);

    // Delete all groups
    router.delete("/", groups.deleteAll);

    app.use("/api/groups", router);
};
